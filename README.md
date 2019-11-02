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

# Limitations

It is not actually practical to create an Auto Scaling Group (ASG) for each instance type in a region duplicated across availability zones and with both on-demand and spot pricing. Running the example included here will create 986 distinct ASGs on your account. AWS sets default limits on the number of ASGs to 200 per region. Additionally, the number of inbound / outbound rules for security groups is limited to 60 by default. `eksctl` will create a security group for Kubernetes control plane communication which will have 1 inbound and 2 outbound rules per `eksctl` generated nodegroup. Since AWS sets a default limit of 60 rules / security group this effectively limits the number of ASGs to 20. Increasing this limit to the maximum of 1000 still limits the number of ASGs to 333. A workaround to this could include placing all nodes into the same security group so only 1 rule needs to be made for control plane communication between all nodes. 
