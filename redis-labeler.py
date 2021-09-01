#!/usr/bin/env python

import argparse
import logging
import subprocess
import time

from kubernetes import config, client


def dict_to_parameter(d):
    items = []
    for key in d.keys():
        items.append(str(key) + '=' + str(d[key]))
    return ','.join(items)


def get_redis_master_svc_ip(redis_host, sentinel_port, sentinel_cluster_name):
    result_1 = subprocess.run(
        [
            'redis-cli', '-h', redis_host, '-p', str(sentinel_port),
            'sentinel', 'get-master-addr-by-name', sentinel_cluster_name
        ],
        stdout=subprocess.PIPE
    )
    result_2 = subprocess.run(['sed', '-n', '1p'], input=result_1.stdout, stdout=subprocess.PIPE)
    result_3 = subprocess.run(['grep', '-E', '[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}'], input=result_2.stdout,
                              stdout=subprocess.PIPE)
    return str(result_3.stdout.decode('utf-8'))


def get_redis_pods_with_roles(k8s_api, master_svc_ip):
    logging.info("received master svc ip:" + master_svc_ip)
    services = k8s_api.list_namespaced_service(namespace=args.namespace,
                                               field_selector="metadata.name={}".format(args.headless_name))
    roles = []
    for service in services.items:
        selectors = service.spec.selector
        pods = k8s_api.list_namespaced_pod(namespace=args.namespace, label_selector=dict_to_parameter(selectors))
        for pod in pods.items:
            if pod.status.pod_ip == str(master_svc_ip.strip()):
                roles.append(("master", pod.metadata.name))
            else:
                roles.append(("slave", pod.metadata.name))
    return roles


def label_redis_pods(k8s_api, pod_name, label):
    logging.info(f"applying label '{label}' to {pod_name}")
    return k8s_api.patch_namespaced_pod(name=pod_name, namespace="{}".format(args.namespace), body=label)


def generate_pod_label_body(label, domain):
    patch_content = {"kind": "Pod", "apiVersion": "v1", "metadata": {"labels": {f"{domain}/role": label}}}
    return patch_content


def find_redis_and_label(v1):
    master_ip = get_redis_master_svc_ip(args.headless_name + '.' + args.namespace, args.sentinel_port,
                                        args.cluster_name)
    logging.info('Master Is: ' + master_ip)
    pod_details = get_redis_pods_with_roles(v1, master_ip)
    for pod_data in pod_details:
        logging.debug(f"POD:  {pod_data[0]}, {pod_data[1]}")
        label_redis_pods(v1, pod_data[1], generate_pod_label_body(pod_data[0], args.domain))


# MAIN
parser = argparse.ArgumentParser(description="Checking redis pods and labelling them with master/ slave accordingly")
parser.add_argument('--dry-run', dest='dry_run', action='store_true', default=False)
parser.add_argument('--namespace', dest='namespace', required=False, default='redis')
parser.add_argument('--redis-cluster-name', dest='cluster_name', required=True)
parser.add_argument('--redis-headless-svc-name', dest='headless_name', required=True)
parser.add_argument('--redis-sentinel-port', dest='sentinel_port', default=26379, required=False)
parser.add_argument('--company-domain', dest='domain', default='ltn-cache', required=False)
parser.add_argument('--config-file', dest='config_file', required=False)
parser.add_argument('--incluster-config', dest='incluster_config', action='store_true', required=False, default=False)
parser.add_argument('--insecure-skip-tls-verify', dest='skip_tls_verify', action='store_true', required=False,
                    default=False)
parser.add_argument('--verbose', dest='verbose', action='store_true', required=False, default=False)
parser.add_argument('--update-period', dest='sleep_seconds', required=False, default=60)

args = parser.parse_args()

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.DEBUG if args.verbose else logging.INFO
)

logging.captureWarnings(True)
logging.info("Starting redis replica labeler...")
logging.info(f"Dry run: {args.dry_run}")

if args.config_file is None:
    logging.info("Loading current kubernetes cluster config")
    config.load_incluster_config()
else:
    logging.info("Loading kubernetes from passed config file")
    config.load_kube_config(config_file=args.config_file)

logging.info(f"SSL Verify: {not args.skip_tls_verify}")
if args.skip_tls_verify:
    conf = client.Configuration()
    conf.verify_ssl = False
    conf.debug = False
    client.Configuration.set_default(conf)

v1Api = client.CoreV1Api()

while True:
    find_redis_and_label(v1Api)
    logging.info(f"Sleeping {args.sleep_seconds}...")
    time.sleep(int(args.sleep_seconds))
