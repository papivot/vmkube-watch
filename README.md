# vmkube-watch

## Project Description
**vmkube-watch** is a Kubernetes controller/watcher that monitors specified Kubernetes resources for ADDED, MODIFIED, or DELETED events. Upon detecting an event, it executes user-defined scripts in corresponding subdirectories (`/app/added`, `/app/modified`, `/app/deleted`). This allows for custom, event-driven automation within a Kubernetes cluster.

## Purpose
The primary purpose is to provide a flexible way to react to changes in Kubernetes resources without writing a complete custom controller in Go. It's useful for operational tasks, notifications, or simple automation triggered by resource lifecycle events.

## Prerequisites
- Docker is installed and running.
- A Kubernetes cluster (e.g., Minikube, Kind, or a cloud provider's K8s service).
- `kubectl` is configured to communicate with your cluster.

## Configuration (Environment Variables)
- `INCLUSTER_CONFIG`: Set to "1" to use in-cluster Kubernetes configuration (service account). If not set or set to something else, it will attempt to use a local kubeconfig file.
- `GROUPANDVERSION`: The API group and version of the resource to watch (e.g., "v1" for core types like Services, "apps/v1" for Deployments).
- `RESOURCETYPE`: The plural name of the resource type to watch (e.g., "services", "deployments", "pods").
- `NAMESPACE`: (Optional) The namespace to watch. If empty or not set, it will watch resources across all namespaces (requires appropriate cluster-wide permissions).
- `MQTTBROKER`: (Optional) Address of an MQTT broker (e.g., "mqtt.eclipse.org").
- `MQTTPORT`: (Optional) Port of the MQTT broker (default: "1883").
- `MQTTTOPIC`: (Optional) MQTT topic to publish event messages to. MQTT features are enabled only if `MQTTBROKER` and `MQTTTOPIC` are set.

## Building and Running the Docker Image
- `cd source`
- `docker build -t vmkube-watch:latest .`
- Example run (for local testing, assuming local kubeconfig): `docker run -e GROUPANDVERSION="v1" -e RESOURCETYPE="pods" -v ~/.kube:/root/.kube:ro vmkube-watch:latest` (Note: The Dockerfile user `appuser` might need write access to `/user/appuser` if Python caching is involved there, or adjust HOME. The current Dockerfile sets `HOME` to `/user/appuser`, but `appuser` might not have a home dir created. The `cache-volume` in k8s handles this by mounting an `emptyDir`.

## Deploying to Kubernetes
- Create a namespace (e.g., vmkube-watch)
- Review and modify `source/kubedeployment.yaml` as needed (e.g., namespace, ConfigMap scripts).
- `kubectl apply -f source/kubedeployment.yaml -n <your-namespace>` (ensure the namespace exists or create it).

## Custom Scripts
- Place executable scripts (e.g., shell scripts) in the `/app/added`, `/app/modified`, or `/app/deleted` directories (as mounted from the ConfigMap `vmkube-watch-cm` in the default deployment).
- When a Kubernetes event occurs for the watched resource, the corresponding script(s) in the relevant directory will be executed.
- The event object (as a JSON string) is passed to the script via the environment variable `CHANGED_VARIABLE`. Scripts can parse this using tools like `jq`.

## Kubernetes RBAC
- The `kubedeployment.yaml` sets up a `ServiceAccount` (`vmkube-watch-sa`), `ClusterRole` (`vmkube-watch-cr`), and `ClusterRoleBinding` (`vmkube-watch-crb`).
- By default, the ClusterRole grants `get`, `list`, `watch` permissions on *all* resources (`*.*`) and non-resource URLs. This is very broad. For production, it's highly recommended to restrict this to only the specific resources the controller needs to watch. For example, if watching only pods within a particular namespace, the Role/ClusterRole should reflect that.
