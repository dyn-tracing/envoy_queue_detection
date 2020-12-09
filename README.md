# Install
This repository primarily relies on Minikube and GCP to model scenarios. We primarily rely on Ubuntu 18.04 for our tests. For convenience, dependencies can be installed with the `./tools/setup.sh` command.

## Package Dependencies (Minikube)
- `kubernetes` to administrate and run web applications in a cluster
- `minikube` to run a local Kubernetes cluster
- `docker` as the container driver back end of Minikube
- `bazel` to build Wasm filters for Envoy
- `istio` to manage Envoy and its filters
- `python3.6` to run the scripts

## Package Dependencies (GCP)


## Python Dependencies
- `prometheus-api-client` to query Prometheus


# Demo

