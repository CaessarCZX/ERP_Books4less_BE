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
            'series_desc', 'pallet_id',
            'item_id', 'item_desc',
            'us_price', 
            'quantity'
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
    from datetime import datetime
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import Table, TableStyle
    from reportlab.pdfgen import canvas
    import pandas as pd
    import os

    try:
        if form_data is None:
            form_data = {}

        # Columnas requeridas
        required = ['series_desc','pallet_id','item_id','item_desc','us_price','quantity']

        # Leer datos
        ext = os.path.splitext(input_file)[1].lower()
        if ext == '.xlsx':
            df = pd.read_excel(input_file, engine='openpyxl')
        elif ext == '.csv':
            df = pd.read_csv(input_file)
        else:
            return {"error": "Formato de archivo no soportado"}

        miss = [c for c in required if c not in df.columns]
        if miss:
            return {"error": f"Faltan columnas: {', '.join(miss)}"}

        # Limpieza y cálculos
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        df['us_price']  = pd.to_numeric(df['us_price'],  errors='coerce').fillna(0)
        df['Extended Retail'] = df['quantity'] * df['us_price']
        df['Extended @ %']    = df['Extended Retail'] * (discount_percent / 100)
        df['Extended Price']  = df['Extended @ %'] * df['quantity']

        # Agrupar por pallet_id
        grouped = df.groupby('pallet_id').agg({
            'series_desc':'first',
            'quantity':'sum',
            'Extended Price':'sum'
        }).reset_index()

        # Inicializar canvas
        c = canvas.Canvas(output_pdf, pagesize=letter)
        width, height = letter

        # Prepara filas de productos
        product_rows = []
        max_desc = 40
        for i, row in grouped.iterrows():
            desc = str(row['series_desc'])
            if len(desc)>max_desc:
                desc = desc[:max_desc]+"..."
            product_rows.append([
                i+1,
                row['pallet_id'],
                desc,
                int(row['quantity']),
                f"${row['Extended Price']:,.2f}"
            ])

        # Totales
        total_qty = int(grouped['quantity'].sum())
        total_ext = grouped['Extended Price'].sum()
        total_row = ["","","TOTAL:", total_qty, f"${total_ext:,.2f}"]

        # Parámetros de tabla y paginación
        header = ["L/N","Item Number","Description","Ordered","Ext. Price"]
        y0      = height - 300
        margin  = 50
        row_h   = 18
        per_pg  = int((y0 - margin)/row_h) - 1

        # Fragmentar y dibujar cada página
        chunks = [product_rows[i:i+per_pg] for i in range(0, len(product_rows), per_pg)]
        for pi, rows in enumerate(chunks):
            if pi > 0:
                c.showPage()

            # === ENCABEZADO EN TODAS LAS PÁGINAS ===
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, height - 40, "Book For Less LLC")
            c.setFont("Helvetica", 10)
            c.drawString(50, height - 55, "P.O. Box 344")
            c.drawString(50, height - 70, "New York, NY 10001")

            # Purchase Order / Date
            po = [
                ["Purchase Order", form_data.get('purchase_info','N/A')],
                ["Date",           form_data.get('order_date','N/A')]
            ]
            t_po = Table(po, colWidths=[100,100])
            t_po.setStyle(TableStyle([
                ('GRID', (0,0),(-1,-1),1,colors.black),
                ('BACKGROUND',(0,0),(1,0),colors.lightgrey),
                ('ALIGN',(0,0),(-1,-1),'CENTER'),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('FONTSIZE',(0,0),(-1,-1),9),
            ]))
            t_po.wrapOn(c,width,height)
            t_po.drawOn(c, width-275, height-90)

            # Vendor
            vd = [
                ["Vendor:"],
                [form_data.get("seller_name","")],
                [form_data.get("seller_PO","")],
                [form_data.get("seller_address","")]
            ]
            t_vd = Table(vd, colWidths=[225])
            t_vd.setStyle(TableStyle([
                ('GRID',(0,0),(-1,-1),1,colors.black),
                ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('FONTSIZE',(0,0),(-1,-1),9),
                ('LEFTPADDING',(0,0),(-1,-1),4),
            ]))
            t_vd.wrapOn(c,width,height)
            t_vd.drawOn(c,50, height-180)

            # Ship To
            st = [
                ["Ship To:"],
                [form_data.get("company_name","")],
                [form_data.get("company_address","")],
                [form_data.get("company_info","")]
            ]
            t_st = Table(st, colWidths=[225])
            t_st.setStyle(TableStyle([
                ('GRID',(0,0),(-1,-1),1,colors.black),
                ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('FONTSIZE',(0,0),(-1,-1),9),
                ('LEFTPADDING',(0,0),(-1,-1),4),
            ]))
            t_st.wrapOn(c,width,height)
            t_st.drawOn(c, width-300, height-180)

            # Shipping / Payment Terms
            sp = [
                ["Shipping Method","Payment Terms"],
                [form_data.get('shipping_method','N/A'),
                 form_data.get('payment_terms',    'N/A')]
            ]
            t_sp = Table(sp, colWidths=[249,249])
            t_sp.setStyle(TableStyle([
                ('GRID',(0,0),(-1,-1),1,colors.black),
                ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('FONTSIZE',(0,0),(-1,-1),9),
                ('LEFTPADDING',(0,0),(-1,-1),4),
            ]))
            t_sp.wrapOn(c,width,height)
            t_sp.drawOn(c,50, height-250)

            # === TABLA DE PRODUCTOS ===
            y_start = height - 300
            data = [header] + rows
            if pi == len(chunks)-1:
                data.append(total_row)

            tbl = Table(data, colWidths=[30,80,228,70,90])
            tbl.setStyle(TableStyle([
                ('GRID',(0,0),(-1,-1),1,colors.black),
                ('BACKGROUND',(0,0),(-1,0),colors.grey),
                ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('ALIGN',(0,0),(-1,-1),'CENTER'),
                ('ALIGN',(2,1),(2,-1),'LEFT'),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.whitesmoke,colors.white]),
            ]))
            tbl.wrapOn(c, width, height)
            tbl.drawOn(c, 50, y_start - row_h*(len(rows)+1))

        # Pie de página
        c.setFont("Helvetica",8)
        c.drawString(50,30, f"Generated on: {datetime.now():%m/%d/%Y %H:%M}")
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