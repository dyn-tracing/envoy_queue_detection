#!/usr/bin/env python3
import argparse
import logging
import sys
import time
import os
import signal
import csv
from multiprocessing import Process
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

from prometheus_api_client import PrometheusConnect

import util

log = logging.getLogger(__name__)

FILE_DIR = Path(__file__).parent.resolve()
ROOT_DIR = FILE_DIR.parent
ISTIO_DIR = FILE_DIR.joinpath("istio-1.8.0")
ISTIO_BIN = ISTIO_DIR.joinpath("bin/istioctl")
WASME_BIN = FILE_DIR.joinpath("bin/wasme")
PATCHED_WASME_BIN = FILE_DIR.joinpath("bin/wasme_patched")
YAML_DIR = FILE_DIR.joinpath("yaml_crds")
TOOLS_DIR = FILE_DIR.joinpath("tools")

FILTER_NAME = ""
FILTER_DIR = FILE_DIR.joinpath("message_counter")
FILTER_TAG = "1"
FILTER_ID = "test"
CONGESTION_PERIOD = 1607016396875512000
OUTPUT_FILE = "output.csv"
NUM_EXPERIMENTS = 1

# the kubernetes python API sucks, but keep this for later

# from kubernetes import client
# from kubernetes.client.configuration import Configuration
# from kubernetes.utils import create_from_yaml
# from kubernetes.config import kube_config
# def get_e2e_configuration():
#     config = Configuration()
#     config.host = None
#     kube_config.load_kube_config(client_configuration=config)
#     log.info('Running test against : %s' % config.host)
#     return config
# conf = get_e2e_configuration()
# k8s_client = client.api_client.ApiClient(configuration=conf)
# create_from_yaml(k8s_client, f"{bookinfo_dir}/platform/kube/bookinfo.yaml")


def inject_istio():
    cmd = f"{ISTIO_BIN} install --set profile=demo "
    cmd += "--set meshConfig.enableTracing=true --skip-confirmation "
    result = util.exec_process(cmd)
    if result != util.EXIT_SUCCESS:
        return result
    cmd = "kubectl label namespace default istio-injection=enabled --overwrite"
    result = util.exec_process(cmd)
    return result


def deploy_addons():
    apply_cmd = "kubectl apply -f "
    url = "https://raw.githubusercontent.com/istio/istio/release-1.8"
    cmd = f"{apply_cmd} {YAML_DIR}/prometheus-mod.yaml && "
    cmd += f"{apply_cmd} {url}/samples/addons/grafana.yaml "
    # cmd += f"{apply_cmd} {url}/samples/addons/jaeger.yaml && "
    # cmd += f"{apply_cmd} {url}/samples/addons/kiali.yaml || "
    # cmd += f"{apply_cmd} {url}/samples/addons/kiali.yaml"
    result = util.exec_process(cmd)
    if result != util.EXIT_SUCCESS:
        return result

    cmd = "kubectl get deploy -n istio-system -o name"
    deployments = util.get_output_from_proc(cmd).decode("utf-8").strip()
    deployments = deployments.split("\n")
    for depl in deployments:
        wait_cmd = "kubectl rollout status -n istio-system "
        wait_cmd += f"{depl} -w --timeout=180s"
        _ = util.exec_process(wait_cmd)
    log.info("Addons are ready.")
    return util.EXIT_SUCCESS


def bookinfo_wait():
    cmd = "kubectl get deploy -o name"
    deployments = util.get_output_from_proc(cmd).decode("utf-8").strip()
    deployments = deployments.split("\n")
    for depl in deployments:
        wait_cmd = f"kubectl rollout status {depl} -w --timeout=180s"
        _ = util.exec_process(wait_cmd)
    log.info("Bookinfo is ready.")
    return util.EXIT_SUCCESS


def deploy_bookinfo():
    if check_kubernetes_status() != util.EXIT_SUCCESS:
        log.error("Kubernetes is not set up."
                  " Did you run the deployment script?")
        sys.exit(util.EXIT_FAILURE)
    # launch bookinfo
    samples_dir = f"{ISTIO_DIR}/samples"
    bookinfo_dir = f"{samples_dir}/bookinfo"
    apply_cmd = "kubectl apply -f"
    book_cmd = f"{apply_cmd} {bookinfo_dir}"
    cmd = f"{apply_cmd} {YAML_DIR}/bookinfo-mod.yaml && "
    cmd += f"{book_cmd}/networking/bookinfo-gateway.yaml && "
    cmd += f"{book_cmd}/networking/destination-rule-all.yaml && "
    cmd += f"{book_cmd}/networking/destination-rule-all-mtls.yaml && "
    cmd += f"{apply_cmd} {YAML_DIR}/storage-upstream.yaml && "
    cmd += f"{apply_cmd} {YAML_DIR}/productpage-cluster.yaml "
    # disable this and use the non-container version of fortio
    # cmd += f"{apply_cmd}/../httpbin/sample-client/fortio-deploy.yaml "
    result = util.exec_process(cmd)
    bookinfo_wait()
    return result


def remove_bookinfo():
    # launch bookinfo
    samples_dir = f"{ISTIO_DIR}/samples"
    bookinfo_dir = f"{samples_dir}/bookinfo"
    cmd = f"{bookinfo_dir}/platform/kube/cleanup.sh &&"
    cmd += f"kubectl delete -f {YAML_DIR}/storage-upstream.yaml && "
    cmd += f"kubectl delete -f {YAML_DIR}/productpage-cluster.yaml "
    result = util.exec_process(cmd)
    return result


def inject_failure():
    cmd = f"kubectl apply -f {YAML_DIR}/fault-injection.yaml "
    result = util.exec_process(cmd)
    return result


def remove_failure():
    cmd = f"kubectl delete -f {YAML_DIR}/fault-injection.yaml "
    result = util.exec_process(cmd)
    return result


def check_kubernetes_status():
    cmd = "kubectl cluster-info"
    result = util.exec_process(
        cmd, stdout=util.subprocess.PIPE, stderr=util.subprocess.PIPE)
    return result


def start_kubernetes(platform, multizonal):
    if platform == "GCP":
        cmd = "gcloud container clusters create demo --enable-autoupgrade "
        cmd += "--enable-autoscaling --min-nodes=3 "
        cmd += "--max-nodes=10 --num-nodes=5 "
        if multizonal:
            cmd += "--region us-central1-a --node-locations us-central1-b "
            cmd += "us-central1-c us-central1-a "
        else:
            cmd += "--zone=us-central1-a "
    else:
        cmd = "minikube start --memory=8192 --cpus=4 "
    result = util.exec_process(cmd)
    return result


def stop_kubernetes(platform):
    if platform == "GCP":
        cmd = "gcloud container clusters delete "
        cmd += "demo --zone us-central1-a --quiet "
    else:
        # delete minikube
        cmd = "minikube delete"
    result = util.exec_process(cmd)
    return result


def get_gateway_info(platform):
    ingress_host = ""
    ingress_port = ""
    if platform == "GCP":
        cmd = "kubectl -n istio-system get service istio-ingressgateway "
        cmd += "-o jsonpath={.status.loadBalancer.ingress[0].ip} "
        ingress_host = util.get_output_from_proc(
            cmd).decode("utf-8").replace("'", "")

        cmd = "kubectl -n istio-system get service istio-ingressgateway "
        cmd += " -o jsonpath={.spec.ports[?(@.name==\"http2\")].port}"
        ingress_port = util.get_output_from_proc(
            cmd).decode("utf-8").replace("'", "")
    else:
        cmd = "minikube ip"
        ingress_host = util.get_output_from_proc(cmd).decode("utf-8").rstrip()
        cmd = "kubectl -n istio-system get service istio-ingressgateway"
        cmd += " -o jsonpath={.spec.ports[?(@.name==\"http2\")].nodePort}"
        ingress_port = util.get_output_from_proc(cmd).decode("utf-8")

    log.debug("Ingress Host: %s", ingress_host)
    log.debug("Ingress Port: %s", ingress_port)
    gateway_url = f"{ingress_host}:{ingress_port}"
    log.debug("Gateway: %s", gateway_url)

    return ingress_host, ingress_port, gateway_url


def start_fortio(gateway_url):
    # cmd = "kubectl get pods -lapp=fortio -o jsonpath={.items[0].metadata.name}"
    # fortio_pod_name = util.get_output_from_proc(cmd).decode("utf-8")
    # cmd = f"kubectl exec {fortio_pod_name} -c fortio -- /usr/bin/fortio "
    cmd = f"{FILE_DIR}/bin/fortio "
    cmd += "load -c 50 -qps 500 -jitter -t 0 -loglevel Warning "
    cmd += f"http://{gateway_url}/productpage"
    fortio_proc = util.start_process(cmd, preexec_fn=os.setsid)
    return fortio_proc


def setup_bookinfo_deployment(platform, multizonal):
    start_kubernetes(platform, multizonal)
    result = inject_istio()
    if result != util.EXIT_SUCCESS:
        return result
    result = deploy_bookinfo()
    if result != util.EXIT_SUCCESS:
        return result
    result = deploy_addons()
    return result


def burst_loop(url):
    NUM_REQUESTS = 500
    MAX_THREADS = 32

    def timeout_request(_):
        try:
            # the timeout effectively makes this request async
            requests.get(url, timeout=0.001)
        except requests.exceptions.ReadTimeout:
            pass

    log.info("Starting burst...")
    # quick hack until I found a better way
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as p:
        for _ in p.map(timeout_request, range(NUM_REQUESTS)):
            pass
    log.info("Done with burst...")


def do_burst(platform):
    _, _, gateway_url = get_gateway_info(platform)
    url = f"http://{gateway_url}/productpage"
    p = Process(target=burst_loop, args=(url, ))
    p.start()
    # do not care about killing that process


def find_congestion(platform, starting_time):
    if check_kubernetes_status() != util.EXIT_SUCCESS:
        log.error("Kubernetes is not set up."
                  " Did you run the deployment script?")
        sys.exit(util.EXIT_FAILURE)
    logs = query_storage(platform)
    if logs == []:
        return None
    if not logs:
        log.info("No congestion found!")
        return None
    # we want to make sure we aren't recording anything earlier
    # than our starting time. That wouldn't make sense
    ival_start = -1
    ival_end = -1
    for idx, (time_stamp, _) in enumerate(logs):
        if int(time_stamp) > starting_time:
            ival_start = idx
            break
    for idx, (time_stamp, _) in enumerate(logs):
        if int(time_stamp) > (starting_time + CONGESTION_PERIOD):
            ival_end = idx
            break
    log_slice = logs[ival_start:ival_end]
    congestion_dict = {}
    for idx, (time_stamp, service_name) in enumerate(log_slice):
        congestion_dict[service_name] = int(time_stamp)
        # we have congestion at more than 1 service
        if len(congestion_dict) > 1:
            for congested_service, congestion_ts in congestion_dict.items():
                congestion_ts_str = util.ns_to_timestamp(congestion_ts)
                log_str = (f"Congestion at {congested_service}"
                           f"at time {congestion_ts_str}")
                log.info(log_str)
            return min(congestion_dict.values())

    log.info("No congestion found")
    return None


def query_storage(platform):
    if platform == "GCP":
        time.sleep(10)  # wait for logs to come in
        logs = []
        cmd = f"{TOOLS_DIR}/logs_script.sh"
        output = util.get_output_from_proc(cmd).decode("utf-8").split("\n")
        for line in output:
            if "Stored" in line:
                line = line[line.find("Stored"):]  # get right after timestamp
                line = line.split()
                timestamp = line[1]
                name = line[-1]
                logs.append([timestamp, name])
    else:
        storage_content = requests.get("http://localhost:8090/list")
        output = storage_content.text.split("\n")
        logs = []
        for line in output:
            if "->" in line:
                line_time, line_name = line.split("->")
                logs.append([line_time, line_name])
    return sorted(logs, key=lambda tup: tup[0])


def launch_prometheus():
    if check_kubernetes_status() != util.EXIT_SUCCESS:
        log.error("Kubernetes is not set up."
                  " Did you run the deployment script?")
        sys.exit(util.EXIT_FAILURE)
    cmd = "kubectl get pods -n istio-system -lapp=prometheus "
    cmd += " -o jsonpath={.items[0].metadata.name}"
    prom_pod_name = util.get_output_from_proc(cmd).decode("utf-8")
    cmd = f"kubectl port-forward -n istio-system {prom_pod_name} 9090"
    prom_proc = util.start_process(cmd, preexec_fn=os.setsid)
    time.sleep(2)
    prom_api = PrometheusConnect(url="http://localhost:9090", disable_ssl=True)

    return prom_proc, prom_api


def launch_storage_mon():
    if check_kubernetes_status() != util.EXIT_SUCCESS:
        log.error("Kubernetes is not set up."
                  " Did you run the deployment script?")
        sys.exit(util.EXIT_FAILURE)
    cmd = "kubectl get pods -lapp=storage-upstream "
    cmd += " -o jsonpath={.items[0].metadata.name}"
    storage_pod_name = util.get_output_from_proc(cmd).decode("utf-8")
    cmd = f"kubectl port-forward {storage_pod_name} 8090:8080"
    storage_proc = util.start_process(cmd, preexec_fn=os.setsid)
    # Let settle things in a bit
    time.sleep(2)

    return storage_proc


def query_csv_loop(prom_api):
    with open("prom.csv", "w+") as csvfile:
        writer = csv.writer(csvfile, delimiter=',')
        writer.writerow(["Time", "RPS"])
        while True:
            query = prom_api.custom_query(
                query="(histogram_quantile(0.50, sum(irate(istio_request_duration_milliseconds_bucket{reporter=\"source\",destination_service=~\"productpage.default.svc.cluster.local\"}[1m])) by (le)) / 1000) or histogram_quantile(0.50, sum(irate(istio_request_duration_seconds_bucket{reporter=\"source\",destination_service=~\"productpage.default.svc.cluster.local\"}[1m])) by (le))")
            for q in query:
                val = q["value"]
                latency = float(val[1]) * 1000
                query_time = util.datetime.fromtimestamp(val[0])
                log.info("Time: %s 50pct Latency (ms) %s", query_time, latency)
                query_ns = f"{val[0] * util.TO_NANOSECONDS:.7f}"
                writer.writerow([query_ns, latency])
                csvfile.flush()
            time.sleep(1)


def check_congestion(platform, writer, congestion_ts):
    detection_ts = find_congestion(platform, congestion_ts)
    if detection_ts is None:
        writer.writerow(["no", "." * 5])
        log.info("No congestion caused")
        return
    log.info("Sent burst at %s recorded it at %s",
             util.ns_to_timestamp(congestion_ts), util.ns_to_timestamp(detection_ts))
    latency = (int(detection_ts) - int(congestion_ts))
    log.info("Latency between sending and recording in storage is %s seconds",
             (latency / util.TO_NANOSECONDS))
    with open("prom.csv", "r") as prom:
        avg = 0
        num_of_recordings = 0
        read = csv.reader(prom)
        next(read, None)  # skip the headers
        for line in read:
            timestamp = float(line[0])
            if detection_ts > timestamp > congestion_ts:
                num_of_recordings += 1
        if num_of_recordings != 0:
            avg = avg / num_of_recordings
        writer.writerow(["yes", congestion_ts, detection_ts, latency,
                         (latency / util.TO_NANOSECONDS), avg])


def do_multiple_runs(platform, num_experiments, output_file):
    with open(output_file, "w+") as csvfile:
        writer = csv.writer(csvfile, delimiter=' ')
        writer.writerow(["found congestion?", "congestion started",
                         "congested detected",
                         "difference in nanoseconds",
                         "difference in seconds",
                         "average load between inducing and detecting congestion"])
        for _ in range(int(num_experiments)):
            time.sleep(15)
            # once everything has started, retrieve the necessary url info
            congestion_ts = time.time() * util.TO_NANOSECONDS
            log.info("Injecting latency at time %s",
                     util.ns_to_timestamp(congestion_ts))
            inject_failure()
            time.sleep(15)
            log.info("Removing latency at time %s", util.nano_ts())
            remove_failure()
            time.sleep(15)
            log.info("Done at time %s", util.nano_ts())
            # process results
            check_congestion(platform, writer, congestion_ts)
            # sleep long enough that the congestion times will not be mixed up
            time.sleep(5)


def do_experiment(platform, num_experiments, output_file):
    if check_kubernetes_status() != util.EXIT_SUCCESS:
        log.error("Kubernetes is not set up."
                  " Did you run the deployment script?")
        sys.exit(util.EXIT_FAILURE)

    # clean up any proc listening on 9090 just to be safe
    cmd = "lsof -ti tcp:9090 | xargs kill || exit 0"
    _ = util.exec_process(
        cmd, stdout=util.subprocess.PIPE, stderr=util.subprocess.PIPE)

    # clean up any proc listening on 8090 just to be safe
    cmd = "lsof -ti tcp:8090 | xargs kill || exit 0"
    _ = util.exec_process(
        cmd, stdout=util.subprocess.PIPE, stderr=util.subprocess.PIPE)

    # once everything has started, retrieve the necessary url info
    _, _, gateway_url = get_gateway_info(platform)
    # set up storage to query later
    log.info("Forwarding storage port at time %s", util.nano_ts())
    storage_proc = launch_storage_mon()
    # start fortio load generation
    log.info("Running Fortio at time %s", util.nano_ts())
    fortio_proc = start_fortio(gateway_url)
    # start Prometheus and wait a little to stabilize
    log.info("Starting Prometheus monitor at time %s", util.nano_ts())
    prom_proc, prom_api = launch_prometheus()
    time.sleep(10)
    p = Process(target=query_csv_loop, args=(prom_api, ))
    p.start()

    do_multiple_runs(platform, num_experiments, output_file)
    log.info("Killing fortio")
    # terminate fortio by sending an interrupt to the process group
    os.killpg(os.getpgid(fortio_proc.pid), signal.SIGINT)
    # kill the storage proc after the query
    log.info("Killing storage")
    os.killpg(os.getpgid(storage_proc.pid), signal.SIGINT)
    # kill prometheus
    log.info("Killing prometheus.")
    p.terminate()
    os.killpg(os.getpgid(prom_proc.pid), signal.SIGINT)


def build_filter(filter_dir, filter_name):
    # Bazel is obnoxious, need to explicitly change dirs
    log.info("Building filter...")
    cmd = f"cd {filter_dir}; bazel build //:filter.wasm"
    result = util.exec_process(cmd)
    if result != util.EXIT_SUCCESS:
        return result

    cmd = f"{PATCHED_WASME_BIN} build precompiled"
    cmd += f" {filter_dir}/bazel-bin/filter.wasm "
    cmd += f"--tag {filter_name}:{FILTER_TAG}"
    cmd += f" --config {filter_dir}/runtime-config.json"
    result = util.exec_process(cmd)
    log.info("Done with building filter...")
    if result != util.EXIT_SUCCESS:
        return result

    log.info("Pushing the filter...")
    cmd = f"{PATCHED_WASME_BIN} push {filter_name}:{FILTER_TAG}"
    result = util.exec_process(cmd)
    # Give it some room to breathe
    time.sleep(2)
    return result


def undeploy_filter(filter_name):
    cmd = f"kubectl delete -f {YAML_DIR}/istio-config.yaml ; "
    cmd += f"kubectl delete -f {YAML_DIR}/virtual-service-reviews-balance.yaml "
    util.exec_process(cmd)
    cmd = f"{WASME_BIN} undeploy istio {filter_name}:{FILTER_TAG} "
    cmd += f"–provider=istio --id {FILTER_ID} "
    cmd += "--labels \"app=reviews\" "
    result = util.exec_process(cmd)
    if result != util.EXIT_SUCCESS:
        return result
    bookinfo_wait()
    return result


def deploy_filter(filter_name):
    # first deploy with the unidirectional wasme binary
    cmd = f"{WASME_BIN} deploy istio {filter_name}:{FILTER_TAG} "
    cmd += f"–provider=istio --id {FILTER_ID} "
    cmd += "--labels \"app=reviews\" "
    result = util.exec_process(cmd)
    if result != util.EXIT_SUCCESS:
        return result
    bookinfo_wait()
    # after we have deployed with the working wasme, remove the deployment
    undeploy_filter(filter_name)
    # now redeploy with the patched bidirectional wasme
    cmd = f"{PATCHED_WASME_BIN} deploy istio {filter_name}:{FILTER_TAG} "
    cmd += f"–provider=istio --id {FILTER_ID} "
    cmd += "--labels \"app=reviews\" "
    result = util.exec_process(cmd)
    bookinfo_wait()
    # apply our customization configuration to the mesh
    cmd = f"kubectl apply -f {YAML_DIR}/istio-config.yaml && "
    cmd += f"kubectl apply -f {YAML_DIR}/virtual-service-reviews-balance.yaml "
    result = util.exec_process(cmd)

    return result


def refresh_filter(filter_dir, filter_name):
    result = build_filter(filter_dir, filter_name)
    if result != util.EXIT_SUCCESS:
        return result
    result = undeploy_filter(filter_name)
    if result != util.EXIT_SUCCESS:
        # A failure here is actually okay
        log.warning("Undeploying failed.")
    result = deploy_filter(filter_name)
    return result


def handle_filter(args):
    is_filter_related = args.build_filter or args.deploy_filter
    is_filter_related = is_filter_related or args.undeploy_filter
    is_filter_related = is_filter_related or args.refresh_filter
    if not is_filter_related:
        return
    if not args.filter_name:
        log.error("The filter name is required to deploy filters with wasme. "
                  "You can set it with the -fn or --filter-name argument.")
        sys.exit(util.EXIT_FAILURE)
    if args.build_filter:
        result = build_filter(args.filter_dir, args.filter_name)
        sys.exit(result)
    if args.deploy_filter:
        result = deploy_filter(args.filter_name)
        sys.exit(result)
    if args.undeploy_filter:
        result = undeploy_filter(args.filter_name)
        sys.exit(result)
    if args.refresh_filter:
        result = refresh_filter(args.filter_dir, args.filter_name)
        sys.exit(result)


def main(args):
    # single commands to execute
    if args.setup:
        return setup_bookinfo_deployment(args.platform, args.multizonal)
    if args.deploy_bookinfo:
        return deploy_bookinfo()
    if args.remove_bookinfo:
        return remove_bookinfo()
    handle_filter(args)
    if args.clean:
        return stop_kubernetes(args.platform)
    if args.burst:
        return do_burst(args.platform)

    # experiment zone, experiments run after this point
    if args.full_run:
        result = setup_bookinfo_deployment(args.platform, args.multizonal)
        if result != util.EXIT_SUCCESS:
            return result
        result = deploy_filter(args.filter_name)
        if result != util.EXIT_SUCCESS:
            return result
    # test the fault injection on an existing deployment
    do_experiment(args.platform, args.num_experiments, args.output_file)
    if args.full_run:
        # all done with the test, clean up
        stop_kubernetes(args.platform)
    return util.EXIT_SUCCESS


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log-file", dest="log_file",
                        default="model.log",
                        help="Specifies name of the log file.")
    parser.add_argument("-ll", "--log-level", dest="log_level",
                        default="INFO",
                        choices=["CRITICAL", "ERROR", "WARNING",
                                 "INFO", "DEBUG", "NOTSET"],
                        help="The log level to choose.")
    parser.add_argument("-p", "--platform", dest="platform",
                        default="KB",
                        choices=["MK", "GCP"],
                        help="Which platform to run the scripts on."
                             "MK is minikube, GCP is Google Cloud Compute")
    parser.add_argument("-m", "--multi-zonal", dest="multizonal",
                        action="store_true",
                        help="If you are running on GCP,"
                        " do you want a multi-zone cluster?")
    parser.add_argument("-f", "--full-run", dest="full_run",
                        action="store_true",
                        help="Whether to do a full run. "
                        "This includes setting up bookinfo and Kubernetes"
                        " and tearing it down again.")
    parser.add_argument("-s", "--setup", dest="setup",
                        action="store_true",
                        help="Just do a deployment. "
                        "This means installing bookinfo and Kubernetes."
                        " Do not run any experiments.")
    parser.add_argument("-c", "--clean", dest="clean",
                        action="store_true",
                        help="Clean up an existing deployment. ")
    parser.add_argument("-fn", "--filter-name", dest="filter_name",
                        default=FILTER_NAME,
                        help="The name of the filter to push to the Wasm Hub.")
    parser.add_argument("-fd", "--filter-dir", dest="filter_dir",
                        default=FILTER_DIR,
                        help="The directory of the filter")
    parser.add_argument("-db", "--deploy-bookinfo", dest="deploy_bookinfo",
                        action="store_true",
                        help="Deploy the bookinfo app. ")
    parser.add_argument("-rb", "--remove-bookinfo", dest="remove_bookinfo",
                        action="store_true",
                        help="Remove the bookinfo app. ")
    parser.add_argument("-bf", "--build-filter", dest="build_filter",
                        action="store_true",
                        help="Build the WASME filter. ")
    parser.add_argument("-df", "--deploy-filter", dest="deploy_filter",
                        action="store_true",
                        help="Deploy the WASME filter. ")
    parser.add_argument("-uf", "--undeploy-filter", dest="undeploy_filter",
                        action="store_true",
                        help="Remove the WASME filter. ")
    parser.add_argument("-rf", "--refresh-filter", dest="refresh_filter",
                        action="store_true",
                        help="Refresh the WASME filter. ")
    parser.add_argument("-fc", "--find-congestion", dest="find_congestion",
                        action="store_true",
                        help="Find congestion in the logs. ")
    parser.add_argument("-b", "--burst", dest="burst",
                        action="store_true",
                        help="Burst with HTTP requests to cause"
                        " congestion and queue buildup.")
    parser.add_argument("-ne", "--num-experiments", dest="num_experiments",
                        default=NUM_EXPERIMENTS,
                        help="Number of times to run an experiment. ")
    parser.add_argument("-o", "--output_file", dest="output_file",
                        default=OUTPUT_FILE,
                        help="Where to store the results of the experiments. ")
    # Parse options and process argv
    arguments = parser.parse_args()
    # configure logging
    logging.basicConfig(filename=arguments.log_file,
                        format="%(levelname)s:%(message)s",
                        level=getattr(logging, arguments.log_level),
                        filemode="w")
    stderr_log = logging.StreamHandler()
    stderr_log.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logging.getLogger().addHandler(stderr_log)
    main(arguments)
