import argparse

from utilities.validate import validate_file


def main():

    parser = argparse.ArgumentParser(description="JPGen 🤓.")
    parser.add_argument("file_path", help="Path to the YAML input file")
    args = parser.parse_args()

    try:
        config = validate_file(args.file_path)
    except ValueError as e:
        print(f"Error: {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return
    
    print(f"Processing file: {args.file_path}")

if __name__ == "__main__":

    main()
