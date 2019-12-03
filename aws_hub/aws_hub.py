#!/usr/bin/env python3

# should read / take in configuration and be able to spit out profile list for JupyterHub
# and configuration files for eksctl
# can use ec2_instance_information.py to get all instance types etc. within a region
from ec2_instance_information import get_all_instance_information_for_region
from utils import load_yaml, load_yaml_from_file, dump_yaml, recursive_dict_copy, recursive_rename_values_in_object
import json
import argparse
from copy import deepcopy
import sys

# process:
# - read configuration
# - get all information for region for all instances
# - parse down based on config/requested instances
#   display warnings for availability zone conflicts
# - make eksctl file/profile list from reduced data

def make_profile_list(instance_information):
    # display name
    # description (from hardware information)
    # family (from instance name)
    # category (from hardware)
    # kubespawner_override: from node taints in configuration
    # cpu_limit / mem_limit: from hardware information
    # extra_resource_limits: if gpu, nvidia.com/gpu

    profile_list = []

    for instance_name, instance_info in instance_information.items():
        on_demand_pricing = instance_info['on_demand_pricing']
        hardware = instance_info['hardware']
        display_name = instance_name.replace(".", "-")
        family = instance_name.split(".")[0].upper()
        category = hardware['instanceFamily']
        cpu_str = hardware['vcpu']
        mem_str = hardware['memory']
        storage = hardware['storage']
        gpu = hardware['gpu']
        network_performance = hardware['networkPerformance']

        if gpu:
            description = "{} CPU, {} RAM, {} GPU".format(cpu_str, mem_str, gpu)
        else:
            description = "{} CPU, {} RAM".format(cpu_str, mem_str)
        
        on_demand_price = float(on_demand_pricing['price'])
        if on_demand_price > 0.01:
            on_demand_price_str = "${:.2f}/hour".format(on_demand_price)
        else:
            on_demand_price_str = "${:.3f}/hour".format(on_demand_price)

        profile = {}
        profile['display_name'] = display_name
        profile['family'] = family
        profile['category'] = category
        profile['description'] = description

        aws = {}
        aws['instance_size'] = display_name.split("-")[-1]
        aws['price'] = on_demand_price
        aws['price_description'] = on_demand_price_str
        aws['network'] = network_performance
        aws['cpu'] = cpu_str
        aws['memory'] = mem_str
        aws['storage'] = storage
        aws['gpu'] = gpu
        profile['aws'] = aws
        
        kubespawner_override = {}
        cpu_limit = float(cpu_str)
        cpu_undershoot_ratio = 0.9
        cpu_guarantee = float("{:.1f}".format(float(cpu_str) * cpu_undershoot_ratio))
        cpu_guarantee = float("{:.1f}".format(cpu_limit - 0.5))
        mem_gib = mem_str.split(" ")[0].replace(",", "")
        # GiB = 2^30 bytes, GB = 10^9 bytes
        gib_to_gb = 1e9 / (2**30)
        mem_gb = float(mem_gib) * gib_to_gb
        mem_undershoot_ratio = 0.9
        mem_limit = "{}M".format(int(1e3 * mem_gb * mem_undershoot_ratio))
        mem_guarantee = "{}M".format(int(1e3 * mem_gb * mem_undershoot_ratio))
        kubespawner_override['cpu_limit'] = cpu_limit
        kubespawner_override['cpu_guarantee'] = cpu_guarantee
        kubespawner_override['mem_limit'] = mem_limit
        kubespawner_override['mem_guarantee'] = mem_guarantee
        extra_resource_limits = {}
        if gpu:
            extra_resource_limits['nvidia.com/gpu'] = gpu
        else:
            extra_resource_limits['nvidia.com/gpu'] = '0'
        kubespawner_override['extra_resource_limits'] = extra_resource_limits

        profile['kubespawner_override'] = kubespawner_override

        profile_list.append(profile)
    
    return profile_list

def make_eksctl_file():
    # see nodegroups.py
    pass

class hubFactory():
    default_config = { 
        'region' : 'us-west-2', 
        'avalabilityZones' : ['a', 'b', 'c' , 'd'],
        'operatingSystem' : "Linux",
        'clusterName' : 'eks-cluster',
        'overPayBy' : 0,
    }
    default_group = {
        'families' : None,
        'instances' : None,
        'type' : 'onDemand',
        'separateAvailabilityZones' : False,
        'separateInstances' : False,
        'separateFamilies' : False,
        'nodegroupOverrides' : {},
    }
    default_hub_config = {
        
    }

    config = None
    region_information = None
    hub_instances = None
    hub_family_instances = None
    instance_availability = None
    hub_config = None
    eksctl_config = None
    processed_nodegroups = None

    def __init__(self):
        pass
    
    def query_region_information(self):
        region = self.config['region']
        region_information = get_all_instance_information_for_region(region)
        self.region_information = region_information

        instance_availability = {}
        self.instance_availability = instance_availability
        hub_family_instances = {}
        self.hub_family_instances = hub_family_instances
        # compute the maximum Spot price for each instance
        for instance, instance_information in region_information.items():
            family = instance.split(".")[0]
            instance_type = instance.split(".")[1]

            if family in hub_family_instances.keys():
                hub_family_instances[family].append(instance_type)
            else:
                hub_family_instances[family] = [instance_type]

            spot_prices_for_instance = []
            instance_availability[instance] = []
            if 'spot_pricing' not in instance_information.keys():
                print("WARNING: {instance} not available as a Spot instance.", file=sys.stderr)
                continue
            for az, price in instance_information['spot_pricing'].items():
                if price:
                    spot_prices_for_instance.append(price)
                    # note in which availability zones an instance is not available as well
                    # if unavailable, it's price for that availability zone will be None
                    instance_availability[instance].append(az)
            if len(spot_prices_for_instance) > 0:
                max_price = max(spot_prices_for_instance)
                instance_information['spot_pricing']['maxPrice'] = max_price

    def set_configuration(self, config):
        self.config = deepcopy(self.default_config)
        if 'config' in config.keys():
            recursive_dict_copy(config['config'], self.config)
        
        if 'nodegroupDefaults' in config.keys():
            self.nodegroupDefaults = config['nodegroupDefaults']
        else:
            self.nodegroupDefaults = None
        
        if 'groups' in config.keys():
            self.groups = config['groups']
        else:
            raise Exception("Configuration invalid. Must specify at least one group to make.")

        if 'hubDefaults' in config.keys():
            recursive_dict_copy(config['hubDefaults'], self.default_hub_config)            

    def set_configuration_from_file(self, config_file):
        config = load_yaml_from_file(config_file)
        self.set_configuration(config)

    def apply_defaults_to_groups(self, groups):
        if self.config:
            new_groups = []
            for _group in groups:
                group = deepcopy(self.default_group)
                recursive_dict_copy(_group, group)
                if 'availabilityZones' not in group.keys():
                    group['availabilityZones'] = self.config['availabilityZones']
                group['availabilityZones'] = [self.config['region'] + az for az in group['availabilityZones']]
                new_groups.append(group)
            return new_groups
        else:
            raise Exception("Configuration not set! Use set_configuration or set_configuration_from_file")

    # returns a flattened list of groups with their families separated out
    def separate_families(self, groups):
        if self.hub_family_instances and self.config:
            all_groups = []
            for group in groups:
                if group['separateFamilies'] and group['families']:
                    group_new_groups = []
                    for family in group['families']:
                        new_group = deepcopy(group)
                        new_group['families'] = None
                        try:
                            new_group['instances'] = [family + "." + instance_type for instance_type in self.hub_family_instances[family]]
                        except KeyError:
                            raise Exception(f"WARNING: instance family {family} not available in region {self.config['region']}!")
                        group_new_groups.append(new_group)
                
                    all_groups.append(group_new_groups)
                else:
                    all_groups.append([group])

            return sum(all_groups, [])
        else:
            if not self.config:
                raise Exception("Configuration not set! Use set_configuration or set_configuration_from_file")
            if not self.hub_family_instances:
                print("Region information not queried!", file=sys.stderr)
                print("Trying now...", file=sys.stderr)
                self.query_region_information()
                return self.separate_families(groups)

    def separate_instances(self, groups):
        all_groups = []
        for group in groups:
            if group['separateInstances'] and group['instances']:
                group_new_groups = []
                for instance in group['instances']:
                    new_group = deepcopy(group)
                    new_group['instances'] = [instance]
                    group_new_groups.append(new_group)
            
                all_groups.append(group_new_groups)
            else:
                all_groups.append([group])

        return sum(all_groups, [])

    def separate_availability_zones(self, groups):
        all_groups = []
        for group in groups:
            if group['separateAvailabilityZones'] and group['availabilityZones']:
                group_new_groups = []
                for availability_zone in group['availabilityZones']:
                    new_group = deepcopy(group)
                    new_group['availabilityZones'] = [availability_zone]
                    group_new_groups.append(new_group)
            
                all_groups.append(group_new_groups)
            else:
                all_groups.append([group])

        return sum(all_groups, [])

    def format_nodegroup(self, nodegroup):
        if 'instanceType' in nodegroup.keys():
            instance_name_fmt = nodegroup['instanceType'].replace(".", "-")
        else:
            instance_name_fmt = ""
        
        if 'instancesDistribution' in nodegroup.keys():
            instance_name_fmt = nodegroup['instancesDistribution']['instanceTypes'][0].replace(".", "-")
            instance_names_fmt = ("-".join(nodegroup['instancesDistribution']['instanceTypes'])).replace(".", "-")
        else:
            instance_names_fmt = ""
        
        region_fmt = self.config['region']
        availability_zones_fmt = "-".join(nodegroup['availabilityZones'])
        availability_zones_short_fmt = "".join([az.split(self.config['region'])[-1] for az in nodegroup['availabilityZones']])
        
        def nodegroup_formatter(value):
            return value.format(
                instance_name=instance_name_fmt,
                instance_names=instance_names_fmt,
                region=region_fmt,
                availability_zones=availability_zones_fmt,
                availability_zones_short=availability_zones_short_fmt,
            )
        formatted_nodegroup = deepcopy(nodegroup)
        formatted_nodegroup = recursive_rename_values_in_object(formatted_nodegroup, nodegroup_formatter)
        return formatted_nodegroup

    def get_unique_instances(self, groups):
        unique_instances = []
        for group in groups:
            unique_instances.append(group['instances'])
        unique_instances = sum(unique_instances, [])
        return list(set(unique_instances))

    def create_on_demand_configuration(self, group):
        nodegroup = deepcopy(self.nodegroupDefaults)
        recursive_dict_copy(group['nodegroupOverrides'], nodegroup)
        nodegroup['availabilityZones'] = group['availabilityZones']
        if group['instances']:
            if len(group['instances']) > 1:
                raise Exception("""
                                Cannot create an on-demand nodegroup with more
                                than one instance type!\nGroup causing error:\n
                                """ + dump_yaml(group))
            else:
                nodegroup['instanceType'] = group['instances'][0]
        else:
            raise Exception("No instances in group!\nGroup causing error:\n" + dump_yaml(group))

        return nodegroup

    def create_spot_configuration(self, group):
        nodegroup = deepcopy(self.nodegroupDefaults)
        recursive_dict_copy(group['nodegroupOverrides'], nodegroup)
        nodegroup['availabilityZones'] = group['availabilityZones']
        if group['instances']:
            if 'instancesDistribution' not in nodegroup.keys():
                nodegroup['instancesDistribution'] = {}
            
            instances_distribution = nodegroup['instancesDistribution']
            if 'onDemandBaseCapacity' not in instances_distribution.keys():
                instances_distribution['onDemandBaseCapacity'] = 0
            if 'onDemandPercentageAboveBaseCapacity' not in instances_distribution.keys():
                instances_distribution['onDemandPercentageAboveBaseCapacity'] = 0

            instances_distribution['instanceTypes'] = group['instances']
            
            # find maximum price among the Spot prices of all instances in this group
            max_prices = []
            for instance in group['instances']:
                max_prices.append(self.region_information[instance]['spot_pricing']['maxPrice'])
            max_price = max(max_prices)
            # set maximum price and over pay by a bit
            instances_distribution['maxPrice'] = max_price * (1. + self.config['overPayBy']/100)
            
            # hack to get around spot instances with only 1 instance in its group
            # include the most expensive instance in its family and keep the max price
            # the same so that the expensive one is never scheduled
            if len(group['instances']) == 1:
                family_prices = []
                for instance, instance_information in self.region_information.items():
                    instance_family = instance.split(".")[0]
                    group_family = group['instances'][0].split(".")[0]
                    same_family = instance_family == group_family
                    if same_family:
                        family_prices.append((instance, self.region_information[instance]['spot_pricing']['maxPrice']))

                most_expensive_in_family = sorted(family_prices, key=lambda x : x[1], reverse=True)[0]
                most_expensive_in_family_instance_name = most_expensive_in_family[0]
                
                instances_distribution['instanceTypes'].append(most_expensive_in_family_instance_name)
                # hack to avoid nodegroup with two of the most expensive instances
                # ...just don't allow that as a spot configuration
                if group['instances'][0] == most_expensive_in_family_instance_name:
                    print(f"WARNING: instance {group['instances'][0]} is the most expensive in it's family and cannot be in a spot group by itself!", file=sys.stderr)
                    return None
        else:
            raise Exception("No instances in group!\nGroup causing error:\n" + dump_yaml(group))

        return nodegroup

    def set_hub_instances(self, instances):
        if self.region_information:
            self.hub_instances = {instance : self.region_information[instance] for instance in instances}
        else:
            print("Region information not set!", file=sys.stderr)
            print("Trying now...", file=sys.stderr)
            self.query_region_information()
            return self.set_hub_instances(instances)

    def evaluate_instances_availability_zones(self, groups):
        new_groups = []
        for group in groups:
            new_group = deepcopy(group)
            group_availability_zones = group['availabilityZones']
            
            valid_azs = []
            for az in group_availability_zones:
                instances_in_az = all([az in self.instance_availability[instance] for instance in group['instances']])
                if instances_in_az:
                    valid_azs.append(az)
                else:
                    print(f"WARNING: removing {az} from nodegroup with instances {group['instances']}", file=sys.stderr)
            
            new_group['availabilityZones'] = valid_azs
            
            new_groups.append(new_group)
        return new_groups

    def process_groups(self):
        groups = self.groups

        groups = self.apply_defaults_to_groups(groups)
        groups = self.separate_families(groups)
        groups = self.separate_instances(groups)

        self.set_hub_instances(self.get_unique_instances(groups))
        
        groups = self.evaluate_instances_availability_zones(groups)
        groups = self.separate_availability_zones(groups)

        processed_groups = []
        for group in groups:
            if group['type'] == 'onDemand':
                on_demand_configuration = self.create_on_demand_configuration(group)
                formatted_configuration = self.format_nodegroup(on_demand_configuration)
            elif group['type'] == 'spot':
                try:
                    spot_configuration = self.create_spot_configuration(group)
                    if not spot_configuration:
                        continue
                except ValueError as e:
                    print("WANRING: " + str(e), file=sys.stderr)
                    continue
                formatted_configuration = self.format_nodegroup(spot_configuration)
            else:
                raise Exception("'type' : '{group['type']}' is invalid")
            processed_groups.append(formatted_configuration)
        
        self.processed_nodegroups = processed_groups

    def apply_defaults_to_hub_profiles(self, profiles):
        new_profiles = []
        for profile in profiles:
            new_profile = deepcopy(self.default_hub_config)
            recursive_dict_copy(profile, new_profile)
            new_profiles.append(new_profile)

        return new_profiles

    def format_profile(self, profile):
        if 'display_name' in profile.keys():
            instance_name_fmt = profile['display_name'].replace(".", "-")
        else:
            instance_name_fmt = ""

        region_fmt = self.config['region']

        def profile_formatter(value):
            return value.format(
                instance_name=instance_name_fmt,
                display_name=instance_name_fmt,
                region=region_fmt,
            )
        formatted_profile = deepcopy(profile)
        formatted_profile = recursive_rename_values_in_object(formatted_profile, profile_formatter)
        
        return formatted_profile

    def create_hub_config(self):
        if self.hub_instances:
            profile_list = make_profile_list(self.hub_instances)

            num_profiles = len(profile_list)
            print(f"INFO: Creating {num_profiles} JupyterHub profiles.", file=sys.stderr)

            profile_list = self.apply_defaults_to_hub_profiles(profile_list)

            profile_list = [self.format_profile(profile) for profile in profile_list]

            hub_config = {}
            jupyterhub = {}
            hub_config['jupyterhub'] = jupyterhub
            singleuser = {}
            jupyterhub['singleuser'] = singleuser
            singleuser['profileList'] = deepcopy(profile_list)

            self.profile_list = profile_list
            self.hub_config = hub_config
        else:
            print("Nodegroups not processed!", file=sys.stderr)
            print("Trying now...", file=sys.stderr)
            self.process_groups()
            return self.create_hub_config()

    def create_eksctl_config(self):
        if self.processed_nodegroups:
            num_nodegroups = len(self.processed_nodegroups)
            print(f"INFO: Creating {num_nodegroups} eksctl profiles (AWS ASGs).", file=sys.stderr)

            eksctl_config = { 
                "apiVersion" : "eksctl.io/v1alpha5", 
                "kind" : "ClusterConfig",
                "metadata" : {
                    "name" : self.config['clusterName'],
                    "region" : self.config['region']
                },
                "availabilityZones" : [self.config['region'] + az for az in self.config['availabilityZones']],
                "nodeGroups" : self.processed_nodegroups,
            }

            self.eksctl_config = eksctl_config
        else:
            print("Nodegroups not processed!", file=sys.stderr)
            print("Trying now...", file=sys.stderr)
            self.process_groups()
            return self.create_eksctl_config()

    def dump_hub_config(self):
        if self.hub_config:
            return dump_yaml(self.hub_config)
        else:
            print("Hub configuration not set!", file=sys.stderr)
            print("Trying now...", file=sys.stderr)
            self.create_hub_config()
            return self.dump_hub_config()
    
    def dump_eksctl_config(self):
        if self.eksctl_config:
            return dump_yaml(self.eksctl_config)
        else:
            print("eksctl configuration not set!", file=sys.stderr)
            print("Trying now...", file=sys.stderr)
            self.create_eksctl_config()
            return self.dump_eksctl_config()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', '-f', type=str, help='The configuration file to use.')
    parser.add_argument('--json', '-j', type=str, help='A JSON string containing the configuration to use.')
    parser.add_argument('--hub_out', '-ho', type=str, help='A filename specifying where the hub configuration should be printed to.')
    parser.add_argument('--eksctl_out', '-eo', type=str, help='A filename specifying where the eksctl configuration should be printed to.')

    args = parser.parse_args()

    config_file = args.file
    config_data_json = args.json
    hub_out = args.hub_out
    eksctl_out = args.eksctl_out

    def _print_hub_config(factory, hub_out):
        hub_config = factory.dump_hub_config()
        if hub_out:
            open(hub_out, "w").write(hub_config)
        else:
            print(hub_config)

    def _print_eksctl_config(factory, eksctl_out):
        eksctl_config = factory.dump_eksctl_config()
        if eksctl_out:
            open(eksctl_out, "w").write(eksctl_config)
        else:
            print(eksctl_config)

    factory = hubFactory()

    if config_file and config_data_json:
        parser.error("must pass either a filename or json.")
    elif not config_file and not config_data_json:
        parser.error("must pass at least one of a filename or json.")
    elif config_file and not config_data_json:
        factory.set_configuration_from_file(config_file)
    else:
        config_data = json.loads(config_data_json)
        factory.set_configuration(config_data)
    
    if hub_out:
        _print_hub_config(factory, hub_out)
    if eksctl_out:
        _print_eksctl_config(factory, eksctl_out)

if __name__ == "__main__":
    main()
