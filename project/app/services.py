import os
import time
import pandas as pd
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from supabase import create_client
from config.config import Config
import traceback

# Crear cliente de Supabase
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_API_KEY)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Tiempo de expiración del archivo (en minutos)
EXPIRATION_TIME = 5  # Eliminar después de 5 minutos

def delete_old_files():
    current_time = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(file_path):
            file_age = current_time - os.path.getctime(file_path)
            if file_age > EXPIRATION_TIME * 60:
                os.remove(file_path)

def upload_to_supabase(file_path, destination_path):
    """Sube un archivo al almacenamiento de Supabase."""
    try:
        with open(file_path, 'rb') as f:
            response = supabase.storage.from_('uploads').upload(destination_path, f)
        if hasattr(response, 'error') and response.error:
            raise Exception(response.error['message'])
        return response
    except Exception as e:
        print(f"Excepción durante la subida: {e}")
        return None
    
def download_file(path):
    """Descarga un archivo desde Supabase Storage usando la ruta completa (e.g., 'uploads/{user_id}/{filename}')."""
    try:
        # Usar la ruta que se pasa directamente
        response = supabase.storage.from_("uploads").create_signed_url(path, 60)
        # Notar que response ya es un objeto, y lo convertimos a dict con get('signedURL') si es que se comporta como tal.
        # Para simplificar, asumiremos que la respuesta es un dict:
        url = response.get('signedURL') or response.get('signedUrl')
        if url is None:
            return {"error": "No se pudo generar la URL firmada."}
        file_path = os.path.join(DOWNLOAD_FOLDER, os.path.basename(path))
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

def process_file(input_file, discount_percent):
    """Convierte un archivo Excel (.xlsx) a CSV y calcula la columna 'Extended @ %'."""
    try:
        output_csv = os.path.join(DOWNLOAD_FOLDER, "archivo_convertido.csv")
        file_extension = os.path.splitext(input_file)[1].lower()
        
        # Cargar el archivo según su extensión
        if file_extension == ".xlsx":
            df_original = pd.read_excel(input_file, sheet_name=0, engine="openpyxl")
        elif file_extension == ".csv":
            df_original = pd.read_csv(input_file, delimiter=";")  # Asegurando que el delimitador sea ";"
        else:
            return {"error": "Formato de archivo no soportado"}
        
        # Eliminar filas vacías antes de guardar
        df_original.dropna(how='all', inplace=True)  # Eliminar filas donde todos los valores son NaN
        
        # Guardar el archivo Excel convertido a CSV
        df_original.to_csv(output_csv, index=False)
        
        # Calcular la columna 'Extended @ %'
        if 'Extended Retail' in df_original.columns:
            df_original['Extended Retail'] = pd.to_numeric(df_original['Extended Retail'], errors='coerce')  # Convertir a numérico, reemplaza errores con NaN
            df_original['Extended @ %'] = df_original.apply(
                lambda row: row['Extended Retail'] * (discount_percent / 100) if pd.notna(row['Extended Retail']) else 0,
                axis=1
            )
        
        return output_csv
    except Exception as e:
        return {"error": str(e)}


def create_pdf(input_file, output_pdf, discount_percent, form_data=None):
    """Crea un PDF a partir de un archivo CSV o Excel y datos del formulario."""
    try:
        # Detectar el formato del archivo y cargarlo como un DataFrame
        file_extension = os.path.splitext(input_file)[1].lower()
        if file_extension == ".xlsx":
            df = pd.read_excel(input_file, sheet_name=0, engine="openpyxl")
        elif file_extension == ".csv":
            df = pd.read_csv(input_file, delimiter=",")
        else:
            return {"error": "Formato de archivo no soportado"}

        # Asegurar que las columnas relevantes sean numéricas
        df['Extended Retail'] = pd.to_numeric(df['Extended Retail'], errors='coerce')
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')

        # Calcular el descuento y las columnas derivadas
        df["Extended @ %"] = df["Extended Retail"] * (discount_percent / 100)
        df["Total Retail"] = df["Extended Retail"] * df["quantity"]
        df["Total @ %"] = df["Extended @ %"] * df["quantity"]
        df["Diferencia"] = df["Total Retail"] - df["Total @ %"]

        # Agrupar por 'pallet_id' para sumar totales por categoría
        grouped = df.groupby("pallet_id").agg({
            "series_desc": "first",
            "quantity": "sum",
            "Total Retail": "sum",
            "Total @ %": "sum",
            "Diferencia": "sum"
        }).reset_index()

        # Crear el PDF con ReportLab
        c = canvas.Canvas(output_pdf, pagesize=letter)
        y_position = 750

        # Información del formulario
        if form_data:
            c.drawString(100, y_position, f"Purchase Info: {form_data.get('purchase_info', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Order Date: {form_data.get('order_date', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Seller Name: {form_data.get('seller_name', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Seller PO: {form_data.get('seller_PO', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Seller Address: {form_data.get('seller_address', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Company Name: {form_data.get('company_name', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Company Address: {form_data.get('company_address', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Company Info: {form_data.get('company_info', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Shipping Method: {form_data.get('shipping_method', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Payment Terms: {form_data.get('payment_terms', 'N/A')}")
            y_position -= 15
            c.drawString(100, y_position, f"Discount Rate: {form_data.get('discount_rate', '0')}%")
            y_position -= 30

        # Crear la tabla con los datos agrupados
        table_data = [["L/N", "Pallet ID", "Description", "Quantity", "Total Retail", "Total @ %", "Diferencia"]]
        for i, row in grouped.iterrows():
            table_data.append([
                i + 1,
                row['pallet_id'],
                row['series_desc'],
                row['quantity'],
                f"{row['Total Retail']:.2f}",
                f"{row['Total @ %']:.2f}",
                f"{row['Diferencia']:.2f}"
            ])

        col_widths = [40, 100, 180, 60, 80, 80, 80]
        table = Table(table_data, colWidths=col_widths)
        table_style = TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ])
        table.setStyle(table_style)
        table.wrapOn(c, 100, y_position)
        table.drawOn(c, 100, y_position - 20)

        # Guardar el PDF
        c.save()
        return {"message": f"PDF creado exitosamente: {output_pdf}"}
    except Exception as e:
        return {"error": str(e)}


def create_csv(input_file, output_csv):
    """Crea un CSV con el conteo de 'item_id'."""
    try:
        df = pd.read_csv(input_file)
        grouped = df.groupby("item_id").agg({
            "series_desc": "first",
            "quantity": "sum"
        }).reset_index()
        grouped.to_csv(output_csv, index=False)
        return {"message": f"CSV creado exitosamente: {output_csv}"}
    except Exception as e:
        return {"error": str(e)}