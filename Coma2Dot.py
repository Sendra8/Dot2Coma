import sys

def replace_dots_with_commas(csv_file):
    # Leer el contenido del archivo como texto
    with open(csv_file, 'r') as file:
        content = file.read()

    # Reemplazar puntos por comas
    content = content.replace(',', '.')

    # Construir el nombre del archivo de salida
    output_file = csv_file.rsplit('.', 1)[0] + '_wDot.csv'

    # Guardar el contenido modificado en un nuevo archivo
    with open(output_file, 'w') as file:
        file.write(content)

    print(f"Archivo convertido y guardado como: {output_file}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python script.py <archivo.csv>")
    else:
        replace_dots_with_commas(sys.argv[1])