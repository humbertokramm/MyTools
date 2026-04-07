import pyvisa


def select_visa_resource():
    rm = pyvisa.ResourceManager()
    resources = rm.list_resources()

    if not resources:
        print("No VISA instruments found.")
        return None

    print("\nDetected VISA Resources:\n")

    resource_list = []

    for i, res in enumerate(resources):
        try:
            inst = rm.open_resource(res)
            inst.timeout = 2000
            idn = inst.query("*IDN?").strip()
            inst.close()
        except Exception:
            idn = "Unknown instrument"

        resource_list.append((res, idn))
        print(f"[{i}] {res}")
        print(f"     {idn}\n")

    if len(resource_list) == 1:
        print("Only one instrument found. Auto-selecting it.\n")
        return resource_list[0][0]

    # Multiple instruments → ask user
    while True:
        try:
            selection = int(input("Select instrument number: "))
            if 0 <= selection < len(resource_list):
                return resource_list[selection][0]
            else:
                print("Invalid selection.")
        except ValueError:
            print("Enter a valid number.")


if __name__ == "__main__":
    selected_resource = select_visa_resource()

    if selected_resource:
        print("\nSelected RESOURCE:")
        print(selected_resource)