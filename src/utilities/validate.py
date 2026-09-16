import yaml


def validate_file(file_path):
    if not file_path.endswith(".yaml"):
        raise ValueError("Input file must be a YAML file")

    try:
        with open(file_path, "r") as file:
            content = yaml.safe_load(file)
            #TODO: Agregar mas validaciones a medida que agregue modulos

            if content is None:
                raise ValueError("YAML file is empty")
            
            print(f"YAML content loaded successfully: {content}")
            
    except Exception as e:
        raise ValueError(f"Error reading YAML file: {e}")

    return content
