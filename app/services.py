import os
import time
import pandas as pd
import requests
import csv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from supabase import create_client
from config.config import Config
from datetime import datetime

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
        # Crear estructura de carpetas si no existe
        folder = "/".join(destination_path.split("/")[:-1])
        try:
            supabase.storage.from_('uploads').list(folder)
        except:
            # Si falla, asumimos que la carpeta no existe
            supabase.storage.from_('uploads').create_folder(folder)
            
        with open(file_path, 'rb') as f:
            response = supabase.storage.from_('uploads').upload(destination_path, f)
        return response
    except Exception as e:
        print(f"Error al subir archivo: {e}")
        return None

def download_file_from_supabase(supabase_path, local_path):
    """Descarga un archivo de Supabase Storage"""
    try:
        # Obtener URL firmada
        res = supabase.storage.from_('files').create_signed_url(supabase_path, 3600)  # 1 hora de validez
        if not res:
            return None
        
        # Descargar el archivo
        response = requests.get(res['signed_url'])
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        print(f"Error al descargar de Supabase: {e}")
        return None
    
def clean_numeric_column(series):
    """
    Limpia una serie numérica eliminando signos de dólar, comas y espacios,
    y luego la convierte a numérico.
    """
    # Convertir a cadena y quitar $ y comas
    cleaned = series.astype(str).replace({'\$': '', ',': '', ' ': ''}, regex=True)
    return pd.to_numeric(cleaned, errors='coerce').fillna(0)

def process_file(input_file, discount_percent):
    """Procesa un archivo Excel validando columnas requeridas y calculando campos adicionales."""
    try:
        # Columnas requeridas
        required_columns = [
            'series_code', 'series_desc', 'pallet_id', 'pallet_available_flag',
            'item_id', 'item_desc', 'family_code', 'reporting_group_desc',
            'publisher_desc', 'imprint_desc', 'us_price', 'can_price',
            'pub_date', 'quantity'
        ]
        
        # Leer el archivo
        file_extension = os.path.splitext(input_file)[1].lower()
        if file_extension == ".xlsx":
            df = pd.read_excel(input_file, sheet_name=0, engine="openpyxl")
        elif file_extension == ".csv":
            df = pd.read_csv(input_file, delimiter=";")
        else:
            return {"error": "Formato de archivo no soportado"}
        
        # Validar columnas requeridas
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return {"error": f"Faltan columnas requeridas: {', '.join(missing_columns)}"}
        
        # Limpieza de datos numéricos
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        df['us_price'] = pd.to_numeric(df['us_price'], errors='coerce').fillna(0)
        
        # Calcular columnas derivadas
        df['Extended Retail'] = df['quantity'] * df['us_price']
        df['Extended @ 3%'] = df['Extended Retail'] * (discount_percent / 100)
        
        # Guardar el archivo procesado (en lugar del original)
        output_csv = os.path.join(DOWNLOAD_FOLDER, "archivo_procesado.csv")
        df.to_csv(output_csv, index=False)
        
        return output_csv
    except Exception as e:
        return {"error": str(e)}

def create_pdf(input_file, output_pdf, discount_percent, form_data=None):
    """Crea un PDF a partir de un archivo CSV o Excel y datos del formulario.
    La salida incluye tablas para:
      - Información de Vendor y Ship To.
      - Shipping Method y Payment Terms en una tabla adicional.
      - Productos (con columnas L/N, Item Number, Description, Ordered y Ext. Price).
    
    Cambios implementados:
    - Validación de columnas requeridas
    - Cálculo automático de Extended Retail (quantity * us_price)
    - Cálculo de Extended @ % basado en el descuento
    - Agrupación por pallet_id para el resumen
    """
    try:
        # Columnas requeridas
        required_columns = [
            'series_code', 'series_desc', 'pallet_id', 'pallet_available_flag',
            'item_id', 'item_desc', 'family_code', 'reporting_group_desc',
            'publisher_desc', 'imprint_desc', 'us_price', 'can_price',
            'pub_date', 'quantity'
        ]
        
        # Leer archivo de entrada
        file_extension = os.path.splitext(input_file)[1].lower()
        if file_extension == ".xlsx":
            df = pd.read_excel(input_file, sheet_name=0, engine="openpyxl")
        elif file_extension == ".csv":
            df = pd.read_csv(input_file, delimiter=",")
        else:
            return {"error": "Formato de archivo no soportado"}
        
        # Validar columnas requeridas
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return {"error": f"Faltan columnas requeridas: {', '.join(missing_columns)}"}

        # Limpieza de datos numéricos
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        df['us_price'] = pd.to_numeric(df['us_price'], errors='coerce').fillna(0)
        
        # Calcular las columnas derivadas EXACTAMENTE como en tu ejemplo corregido
        df['Extended Retail'] = df['quantity'] * df['us_price']
        df['Extended @ %'] = df['us_price'] * (discount_percent)/100
        df['Extended Price'] = df['Extended @ %'] * df['quantity']  # Nueva columna para el total por item
        
        # Agrupar por pallet_id para el resumen
        grouped = df.groupby('pallet_id').agg({
            'series_desc': 'first',
            'quantity': 'sum',
            'Extended Retail': 'sum',
            'Extended @ %': 'sum',
            'Extended Price': 'sum'  # Suma de Extended @ % * quantity
        }).reset_index()
        
        # Configuración del PDF
        c = canvas.Canvas(output_pdf, pagesize=letter)
        width, height = letter

        # Encabezado de la compañía
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, height - 40, "Book For Less LLC")
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 55, "P.O. Box 344")
        c.drawString(50, height - 70, "New York, NY 10001")
        
        # Tabla para Purchase Order
        po_data = [
            ["Purchase Order", form_data.get('purchase_info', 'N/A')],
            ["Date", form_data.get('order_date', 'N/A')]
        ]
        po_table = Table(po_data, colWidths=[100, 100])
        po_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (0, 1), colors.lightgrey),  # Aplica fondo gris a las primeras dos celdas de la primera columna
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (0, 1), 'Helvetica-Bold'),  # Aplica negrita a todo el encabezado (primeras dos filas)
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        po_table.wrapOn(c, width, height)
        po_table.drawOn(c, width - 275, height - 90)
        
        # Tabla para Vendor
        vendor_data = [
            ["Vendor:"],
            [form_data.get("seller_name", "")],
            [form_data.get("seller_PO", "")],
            [form_data.get("seller_address", "")]
        ]
        vendor_table = Table(vendor_data, colWidths=[225, 225])
        vendor_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
        vendor_table.wrapOn(c, width, height)
        vendor_table.drawOn(c, 50, height - 180)
        
        # Tabla para Ship To
        ship_to_data = [
            ["Ship To:"],
            [form_data.get("company_name", "")],
            [form_data.get("company_address", "")],
            [form_data.get("company_info", "")]
        ]
        ship_to_table = Table(ship_to_data, colWidths=[225, 225])
        ship_to_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        ship_to_table.wrapOn(c, width, height)
        ship_to_table.drawOn(c, width - 300, height - 180)
        
        # Tabla para Shipping Method y Payment Terms
        shipping_data = [
            ["Shipping Method", "Payment Terms"],
            [form_data.get('shipping_method', 'N/A'), form_data.get('payment_terms', 'N/A')]
        ]
        shipping_table = Table(shipping_data, colWidths=[249, 249])
        shipping_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        shipping_table.wrapOn(c, width, height)
        shipping_table.drawOn(c, 50, height - 250)
        
        # Tabla de productos (usando los datos agrupados por pallet_id)
        product_header = ["L/N", "Item Number", "Description", "Ordered", "Ext. Price"]
        product_data = [product_header]
        max_desc_chars = 40  # máximo número de caracteres para la descripción
        
        for i, row in grouped.iterrows():
            desc = str(row['series_desc'])[:max_desc_chars] + "..." if len(str(row['series_desc'])) > max_desc_chars else str(row['series_desc'])
            product_data.append([
                i + 1,
                row['pallet_id'],
                desc,
                int(row['quantity']),
                f"${row['Extended Price']:,.2f}"  # Mostramos el Extended Price sumado
            ])
        
        # Fila de totales
        total_ordered = int(grouped['quantity'].sum())
        total_extended_price = grouped['Extended Price'].sum()
        product_data.append([
            "", "", "TOTAL:",
            total_ordered,
            f"${total_extended_price:,.2f}"
        ])

        col_widths = [30, 80, 228, 70, 90]
        product_table = Table(product_data, colWidths=col_widths)
        product_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ]))
        product_table.wrapOn(c, width, height)
        product_table.drawOn(c, 50, height - 430)

        # Pie de página
        c.setFont("Helvetica", 8)
        c.drawString(50, 30, f"Generated on: {datetime.now().strftime('%m/%d/%Y %H:%M')}")
        c.save()
        return {"message": f"PDF creado exitosamente: {output_pdf}"}
    except Exception as e:
        return {"error": str(e)}
    
def create_csv(input_file, output_csv):
    """
    Crea un CSV agrupado por 'item_id' e 'item_desc', sumando la 'quantity',
    formateando 'item_id' sin notación científica y asegurando que no se repitan.
    """
    try:

        # Leer el archivo según su extensión
        file_extension = os.path.splitext(input_file)[1].lower()
        if file_extension == ".xlsx":
            df = pd.read_excel(input_file, sheet_name=0, engine="openpyxl")
        elif file_extension == ".csv":
            df = pd.read_csv(input_file, delimiter=",")
        else:
            return {"error": "Formato de archivo no soportado"}

        # Asegurarse de que 'item_id' se trate como número para luego formatearlo
        if 'item_id' in df.columns:
            # Si el item_id viene como número, lo convertimos a string sin notación científica
            def format_item_id(x):
                try:
                    # Se convierte a float y luego a entero, asumiendo que es un identificador sin decimales
                    return str(int(float(x)))
                except:
                    return str(x)

            df['item_id'] = df['item_id'].apply(format_item_id)
        else:
            return {"error": "No se encontró la columna 'item_id' en el archivo."}

        # Renombrar 'series_desc' a 'item_desc' si es necesario
        if 'series_desc' in df.columns and 'item_desc' not in df.columns:
            df.rename(columns={'series_desc': 'item_desc'}, inplace=True)
        
        if 'item_desc' not in df.columns:
            return {"error": "No se encontró la columna 'item_desc' en el archivo."}

        # Asegurarse de que 'quantity' sea numérica y reemplazar NaN por 0
        if 'quantity' in df.columns:
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        else:
            return {"error": "No se encontró la columna 'quantity' en el archivo."}

        # Eliminar la columna 'Extended Retail' si existe
        if 'Extended Retail' in df.columns:
            df.drop(columns=['Extended Retail'], inplace=True)

        # Agrupar por 'item_id' e 'item_desc', sumando 'quantity'
        grouped_df = df.groupby(['item_id', 'item_desc'], as_index=False)['quantity'].sum()

        # Guardar el CSV resultante sin índices
        grouped_df.to_csv(output_csv, index=False)

        return {"message": f"CSV creado exitosamente: {output_csv}"}

    except Exception as e:
        return {"error": str(e)}