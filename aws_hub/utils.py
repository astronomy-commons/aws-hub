import yaml
try:
    from yaml import CLoader as yamlLoader, CDumper as yamlDumper
except ImportError:
    from yaml import Loader as yamlLoader, Dumper as yamlDumper

# Loads data into memory from a YAML string
def load_yaml(data_str, Loader=yamlLoader):
    return yaml.load(data_str, Loader=Loader)

def load_yaml_from_file(filename, Loader=yamlLoader):
    with open(filename, "r") as yaml_file:
        file_data = yaml_file.read()
        return load_yaml(file_data, Loader=Loader)

# Dumps data stored as dictionaries and lists into a a YAML string
def dump_yaml(data, Dumper=yamlDumper):
    return yaml.dump(data, Dumper=Dumper)

def recursive_dict_copy(source, target):
    for key, value in source.items():
        if type(value) is dict:
            try:
                recursive_dict_copy(value, target[key])
            except KeyError:
                target[key] = {}
                recursive_dict_copy(value, target[key])
        else:
            target[key] = value

def recursive_rename_values_in_object(obj, formatter):
    def _try_rename_value(value):
        if type(value) == str:
            return formatter(value)
        elif type(value) == dict or type(value) == list:
            return recursive_rename_values_in_object(value, formatter)
        else:
            return value

    if type(obj) == dict:
        ret_obj = {}
        for key, value in obj.items():
            key = _try_rename_value(key)
            ret_obj[key] = _try_rename_value(value)
    elif type(obj) == list:
        ret_obj = []
        for value in obj:
            ret_obj.append(_try_rename_value(value))
    else:
        ret_obj = None
    
    return ret_obj
