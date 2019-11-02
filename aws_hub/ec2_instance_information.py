import argparse
import boto3
import json
from pkg_resources import resource_filename
import datetime
import sys

def map_region_code_to_name(region):
    endpoint_file = resource_filename('botocore', 'data/endpoints.json')
    with open(endpoint_file, 'r') as f:
        data = json.load(f)
    return data['partitions'][0]['regions'][region]['description']

def make_boto3_client(client_type, api_region):
    client = boto3.client(client_type, region_name=api_region)
    return client

def get_all_availability_zones_for_region(region):
    client = make_boto3_client("ec2", region)
    response = client.describe_availability_zones()
    availability_zones = [az_data['ZoneName'] for az_data in response['AvailabilityZones']]
    return availability_zones

def get_instance_information_for_region(region, operating_system="Linux"):
    client = make_boto3_client("pricing", "us-east-1")
    # https://github.com/lyft/awspricing/blob/master/awspricing/__init__.py
    paginator = client.get_paginator('get_products')

    region_name = map_region_code_to_name(region)
    instance_filter = '[{{ "Field" : "location", "Value" : "{region_name}", "Type" : "TERM_MATCH" }},\
                        {{ "Field" : "operatingSystem", "Value" : "{operating_system}", "Type" : "TERM_MATCH" }},\
                        {{ "Field" : "tenancy", "Value" : "shared", "Type" : "TERM_MATCH" }},\
                        {{ "Field" : "preInstalledSw", "Value" : "NA", "Type" : "TERM_MATCH" }},\
                        {{ "Field" : "capacitystatus", "Value" : "Used", "Type" : "TERM_MATCH" }}]'
    instance_filter = instance_filter.format(region_name=region_name, operating_system=operating_system)

    pages = paginator.paginate(ServiceCode="AmazonEC2", Filters=json.loads(instance_filter))

    instance_types = {}
    for page in pages:
        for product in page['PriceList']:
            product_data = json.loads(product)

            instance_type = product_data['product']['attributes']['instanceType']
            sku = product_data['product']['sku']

            instance_types[sku] = { 'name' : instance_type, 'data' : product_data }

    return instance_types


def get_instance_descriptions(instance_information):
    instance_descriptions = {}
    for sku, data in instance_information.items():
        name = data['name']
        instance_data = data['data']
        product = instance_data['product']
        attributes = product['attributes']
                
        instance_descriptions[name] = {}
        for key in ['vcpu', 'memory', 'networkPerformance', 
                    'storage', 'physicalProcessor', 'storage', 'gpu',
                    'clockSpeed']:
            if key in attributes.keys():
                instance_descriptions[name][key] = attributes[key]

    return instance_descriptions

def get_spot_price_for_instance_names(region, availability_zones, instance_names, time_ago=10, operating_system="Linux"):
    if operating_system == "Linux" or operating_system == "Linux/Unix":
        operating_system_description = "Linux/UNIX"
    elif operating_system == "Windows":
        operating_system_description = operating_system
    elif operating_system == "RHEL" or operating_system == "Red Hat Enterprise Linux":
        operating_system_description = "Red Hat Enterprise Linux"
    elif operating_system == "SUSE" or operating_system == "SUSE Linux":
        operating_system_description = "SUSE Linux"
    
    client = make_boto3_client("ec2", region)

    paginator = client.get_paginator('describe_spot_price_history')

    now = datetime.datetime.now()
    past = now - datetime.timedelta(days=time_ago)
    pages = paginator.paginate(InstanceTypes=instance_names, 
                                ProductDescriptions=[operating_system_description],
                                StartTime=past,
                                EndTime=now)

    spot_data = {}
    for page in pages:
        for spot_record in page['SpotPriceHistory']:
            instance_type = spot_record['InstanceType']
            availability_zone = spot_record['AvailabilityZone']

            spot_price = float(spot_record["SpotPrice"])

            try:
                spot_data[instance_type]
            except KeyError:
                spot_data[instance_type] = {}
            try:
                spot_data[instance_type][availability_zone]
            except KeyError:
                spot_data[instance_type][availability_zone] = []
            
            spot_data[instance_type][availability_zone].append(spot_price)

    for instance_type, instance_data in spot_data.items():
        instance_availability_zones = []
        for availability_zone, spot_prices in instance_data.items():
            spot_data[instance_type][availability_zone] = sum(spot_prices) / len(spot_prices)
            instance_availability_zones.append(availability_zone)
        
        availability_zones_extra = [az for az in instance_availability_zones if az not in availability_zones]
        for az in availability_zones_extra:
            spot_data[instance_type].pop(az, None)

        availability_zones_missing = [az for az in availability_zones if az not in instance_availability_zones]
        # if len(availability_zones_missing) != 0:
        #     print("WARNING:", instance_type, "not available in {}".format(" ".join(availability_zones_missing)))
        for az in availability_zones_missing:
            spot_data[instance_type][az] = None

    return spot_data

def get_spot_price_for_instance_families(region, availability_zones, instance_families, time_ago=1, operating_system="Linux"):
    region_instance_info = get_instances_types(region)

    instance_names = []
    for family in instance_families:
        family_instance_names = [ instance_type['name'] for _, instance_type in region_instance_info.items() 
                                    if instance_type['name'].split(".")[0] == family ]
        if len(family_instance_names) == 0:
            print("WARNING: instance family {} had no valid instances in region {}".format(family, region), file=sys.stderr)
        instance_names += family_instance_names
    
    if len(instance_names) == 0:
        raise Exception("No instance families had valid instances in region {}".format(region))
    
    region_families_prices = get_spot_price_for_instance_names(region, availability_zones, instance_names, time_ago=time_ago, operating_system=operating_system)

    return region_families_prices

def get_all_spot_prices(region, availability_zones, time_ago=1, operating_system="Linux"):
    return get_spot_price_for_instance_names(region, availability_zones, [], time_ago=time_ago, operating_system=operating_system)


def get_on_demand_price_for_instance_names(region, availability_zones, instance_names, time_ago=10, operating_system="Linux"):
    pass

def get_spot_prices_for_region(region, operating_system="Linux", time_ago=1):
    availability_zones = get_all_availability_zones_for_region(
        region
    )
    spot_prices = get_all_spot_prices(
        region, 
        availability_zones, 
        operating_system=operating_system,
        time_ago=time_ago
    )
    return spot_prices

def get_on_demand_prices_for_region(region, operating_system="Linux"):
    def get_on_demand_price(instance_info):
        on_demand_pricing = instance_info['terms']['OnDemand']
        instance_id = list(on_demand_pricing.keys())[0]
        instance_price_id = list(on_demand_pricing[instance_id]['priceDimensions'].keys())[0]
        instance_pricing_info = on_demand_pricing[instance_id]['priceDimensions'][instance_price_id]
        price_usd = instance_pricing_info['pricePerUnit']['USD']
        price_description = instance_pricing_info['description']
        return price_usd, price_description
    
    instance_information = get_instance_information_for_region(region, operating_system=operating_system)
    
    pricing_data = {}
    for sku, data in instance_information.items():
        instance_name = data['name']
        # family = instance_name.split(".")[0]
        # instance_type = instance_name.split(".")[1]
        
        on_demand_price, on_demand_price_description = get_on_demand_price(data['data'])
        pricing_data[instance_name] = { 'price' : on_demand_price, 'description' : on_demand_price_description}

    return pricing_data

def get_pricing_info_for_region(region, operating_system="Linux"):
    on_demand_prices = get_on_demand_prices_for_region(region, operating_system=operating_system)
    spot_prices = get_spot_prices_for_region(region, operating_system=operating_system)
    return { "on_demand" : on_demand_prices, "spot" : spot_prices }

def get_instance_hardware_information_for_region(region, operating_system="Linux"):
    instance_descriptions = {}

    instance_information = get_instance_information_for_region(region, operating_system=operating_system)
    for sku, data in instance_information.items():
        instance_name = data['name']
        instance_info = data['data']
        
        product = instance_info['product']
        attributes = product['attributes']

        instance_descriptions[instance_name] = {}
        for key in ['vcpu', 'memory', 'networkPerformance', 
                    'storage', 'physicalProcessor', 'storage', 'gpu',
                    'clockSpeed', 'instanceFamily']:
            if key in attributes.keys():
                instance_descriptions[instance_name][key] = attributes[key]
            else:
                instance_descriptions[instance_name][key] = None

    return instance_descriptions

def get_all_instance_information_for_region(region, operating_system="Linux"):
    pricing_info = get_pricing_info_for_region(
        region, 
        operating_system=operating_system,
    )
    on_demand_pricing = pricing_info['on_demand']
    spot_pricing = pricing_info['spot']

    hardware_info = get_instance_hardware_information_for_region(
        region,
        operating_system=operating_system
    )

    all_instances = set(on_demand_pricing.keys()).union(
        set(spot_pricing.keys())
    ).union(
        set(hardware_info.keys())
    )

    # all_instance_categories = set([info['instanceFamily'] for instance, info in hardware_info.items()])

    # print(all_instance_categories)

    all_instance_information = {}
    for instance_name in all_instances:
        all_instance_information[instance_name] = {}
        if instance_name in on_demand_pricing.keys():
            all_instance_information[instance_name]['on_demand_pricing'] = on_demand_pricing[instance_name]
        else:
            print(f"WARNING: {instance_name} has no On-Demand pricing information.", file=sys.stderr)

        if instance_name in spot_pricing.keys():
            all_instance_information[instance_name]['spot_pricing'] = spot_pricing[instance_name]
        else:
            print(f"WARNING: {instance_name} not availabe in {region} as a Spot instance!", file=sys.stderr)
            all_instance_information[instance_name]['spot_pricing'] = { az : None for az in get_all_availability_zones_for_region(region) }
        
        if instance_name in hardware_info.keys():
            all_instance_information[instance_name]['hardware'] = hardware_info[instance_name]
        else:
            print(f"WARNING: {instance_name} has no hardware information.", file=sys.stderr)

    return all_instance_information