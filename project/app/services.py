import os
import pandas as pd
import requests
from supabase import create_client
from config.config import Config

# Crear cliente de Supabase
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_API_KEY)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def download_file(filename):
    """ Descarga un archivo desde Supabase Storage """
    try:
        response = supabase.storage.from_("uploads").create_signed_url(f"uploads/{filename}", 60)
        url = response.get('signedURL') or response.get('signedUrl')

        if url is None:
            return {"error": "No se pudo generar la URL firmada."}

        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        with requests.get(url, stream=True) as r:
            if r.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                return {"error": "No se pudo descargar el archivo."}

        return file_path

    except Exception as e:
        return {"error": str(e)}

def process_file(input_file):
    """ Procesa un archivo Excel (.xlsx) o CSV y lo convierte a un formato estándar """
    try:
        output_csv = os.path.join(DOWNLOAD_FOLDER, "archivo_corregido.csv")

        # Detectar si es un archivo CSV o Excel
        file_extension = os.path.splitext(input_file)[1].lower()

        if file_extension == ".xlsx":
            df_original = pd.read_excel(input_file, sheet_name=0, engine="openpyxl")
        elif file_extension == ".csv":
            df_original = pd.read_csv(input_file, delimiter=";")  # Ajustar delimitador si es necesario
        else:
            return {"error": "Formato de archivo no soportado"}

        # Definir las columnas esperadas (asegurar que existan en el archivo)
        columnas = ["series_code", "series_desc", "pallet_id", "pallet_available_flag", "item_id", "item_desc",
                    "family_code", "reporting_group_desc", "publisher_desc", "imprint_desc", "us_price", "can_price",
                    "pub_date", "quantity", "Extended Retail", "Extended @ 3%"]

        # Verificar si las columnas están presentes en el archivo
        missing_columns = [col for col in columnas if col not in df_original.columns]
        if missing_columns:
            return {"error": f"Faltan las siguientes columnas: {', '.join(missing_columns)}"}

        # Filtrar solo las columnas necesarias
        df_original = df_original[columnas]

        # Guardar el archivo corregido en formato CSV
        df_original.to_csv(output_csv, index=False)

        return output_csv

    except Exception as e:
        return {"error": str(e)}

def createPdf(extendedpercent):
    palle_id=""
    series_desc=""
    quantity=""
    extended="" #la sumatoria de los precios
    extendedpercent="" #porcentaje de descuento, entregado por el usuario no en el archivo
    #en el archivo pdf debe estar la sumatoria de todos los precios con el descuento aplicado
    return

def createCsv():
    item_id(ISBN)=""
    Title="" 
    quantity=""
    #esta planeado para que saque el conteo de cada item_id independientemente de en que pallet esté y lo guarde en un csv
    return