# Dynamic SLA Monitoring With Envoy

## Install
This repository relies on Minikube and GCP to emulate microservice scenarios. We primarily use Ubuntu 18.04 for our tests. For convenience, dependencies can be installed with the `./tools/setup.sh` command. It contains all the steps necessary to set up the testing environment.

### Package Dependencies (Minikube)
- `kubernetes` to administrate and run web applications in a cluster
- `minikube` to run a local Kubernetes cluster
- `docker` as the container driver back end of Minikube
- `bazel` to build Wasm filters for Envoy
- `istio` to manage Envoy and its filters
- `python3.6` to run the scripts

### Package Dependencies (GCP)
TBD

### Python Dependencies
- `prometheus-api-client` to query Prometheus

## Running Experiments

## Setup
Once everything is installed, the Kubernetes cluster can be started with
`./fault_testing.py --setup`. This will take a couple minutes.

We provide a pre-built filter. It can be deployed with the `./fault_testing.py --filter-name webassemblyhub.io/fruffy/test-filter --deploy-filter ` command.
We are currently working on a solution that deploys locally-built filters.

## Demo
Once the filter has been successfully installed, it is possible to run experiments with  `./fault_testing.py --num-experiments 1`.

## Teardown
Remove the filter

`./fault_testing.py --filter-name webassemblyhub.io/fruffy/test-filter --undeploy-filter`

Remove the bookinfo application

`./fault_testing.py --remove-bookinfo`

Tear down the cluster

`./fault_testing.py --clean`

