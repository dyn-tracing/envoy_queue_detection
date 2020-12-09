# Install
This repository primarily relies on Minikube and GCP to model scenarios. We primarily use Ubuntu 18.04 for our tests. For convenience, dependencies can be installed with the `./tools/setup.sh` command. It contains all the steps necessary to set up the testing environment.

## Package Dependencies (Minikube)
- `kubernetes` to administrate and run web applications in a cluster
- `minikube` to run a local Kubernetes cluster
- `docker` as the container driver back end of Minikube
- `bazel` to build Wasm filters for Envoy
- `istio` to manage Envoy and its filters
- `python3.6` to run the scripts

## Package Dependencies (GCP)
TBD

## Python Dependencies
- `prometheus-api-client` to query Prometheus

# Demo
Once everything is installed, the Kubernetes cluster can be started with
`./fault_testing.py --setup`. This will take a couple minutes.

We provide a pre-built filter. It can be deployed with the `./fault_testing.py --deploy-filter` command.  Once the filter has been successfully installed it is possible to run experiments with  `./fault_testing.py ----num-experiments 1`.






