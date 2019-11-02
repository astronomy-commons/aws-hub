# aws-hub
A JupyterHub on Kubernetes gateway to EC2 instances on AWS

This repository contains a Helm chart in `aws-hub` and a Python module in `aws_hub`.

# Installation
Requires `python3`! Install dependencies either with
```
python -m pip install -r requirements.txt
```
or use a python virtual environment:
```
python3 -m venv my-env
source my-env/bin/activate
python -m pip install -r requirements.txt
```

Set up your environment so you can use the scripts:
```
git clone git@github.com:dirac-institute/aws-hub.git
cd aws-hub
export PATH=$PWD/aws_hub:$PATH
```

# Example usage

Run with one of the examples
```
aws_hub.py --file examples/config.yaml --eksctl_out cluster.yaml --hub_out profiles.yaml
```

Create the EKS cluster with the generated nodegroups
```
eksctl create cluster -f cluster.yaml
```

Install the helm chart
```
# a secret key for the JupyterHub proxy is the minimum requirement to launch the Hub
printf "jupyterhub:\n  proxy:\n    secretToken: $(openssl rand -hex 32)\n" >> secret.yaml
# install the aws-hub helm chart (based on JupyterHub) with the instance profiles and the generated secret
helm upgrade --install aws-hub aws-hub --namespace aws-hub --values profiles.yaml --values secret.yaml
```
