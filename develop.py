from kubernetes import client, config
import logging

config.load_kube_config(config_file="~/.kube/config")
v1Api = client.CoreV1Api()


def dict_to_parameter(d):
    items = []
    for key in d.keys():
        items.append(str(key) + '=' + str(d[key]))
    return ','.join(items)


def get_redis_pods_with_roles(k8s_api, master_svc_ip):
    services = k8s_api.list_namespaced_service(namespace="staging",
                                               field_selector="metadata.name=staging-cache-headless")
    roles = []
    for service in services.items:
        selectors = service.spec.selector
        pods = k8s_api.list_namespaced_pod(namespace='staging', label_selector=dict_to_parameter(selectors))
        for pod in pods.items:
            print(dir(pod))
            print(pod.status.pod_ip)
            print(pod.metadata.name)
            if pod.status.pod_ip == master_svc_ip:
                roles.append(("master", pod.metadata.name))
            else:
                roles.append(("slave", pod.metadata.name))
    return roles


def label_redis_pods(k8s_api, pod_name, label):
    logging.info(f"applying label '{label}' to {pod_name}")
    return k8s_api.patch_namespaced_pod(name=pod_name, namespace="staging", body=label)


def generate_pod_label_body(label, domain):
    patch_content = {"kind": "Pod", "apiVersion": "v1", "metadata": {"labels": {f"{domain}/role": label}}}
    return patch_content


def find_redis_and_label(v1):
    master_ip = "10.0.1.89"
    logging.info('Master Is: ' + master_ip)
    pod_details = get_redis_pods_with_roles(v1, master_ip)
    for pod_data in pod_details:
        logging.debug(f"POD:  {pod_data[0]}, {pod_data[1]}")
        label_redis_pods(v1, pod_data[1], generate_pod_label_body(pod_data[0], "ltn-cache-staging"))


find_redis_and_label(v1Api)
