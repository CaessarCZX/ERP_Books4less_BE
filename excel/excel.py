import pandas as pd
import numpy as np

# Cargar el archivo CSV con el delimitador correcto
df = pd.read_csv("archivo_original.csv", delimiter=';')

# Reemplazar símbolos de moneda, espacios extra, comas y las celdas vacías con NaN en las columnas de precios
df['us_price'] = df['us_price'].replace({r'\$': '', r'\s': '', r',': '', r'-': np.nan, r'': np.nan}, regex=True)
df['can_price'] = df['can_price'].replace({r'\$': '', r'\s': '', r',': '', r'-': np.nan, r'': np.nan}, regex=True)
df['Extended Retail'] = df['Extended Retail'].replace({r'\$': '', r'\s': '', r',': '', r'-': np.nan, r'': np.nan}, regex=True)
df['Extended @ 3%'] = df['Extended @ 3%'].replace({r'\$': '', r'\s': '', r',': '', r'-': np.nan, r'': np.nan}, regex=True)

# Asegurarse de que las celdas vacías sean reemplazadas correctamente por NaN
df['us_price'] = df['us_price'].replace('', np.nan)
df['can_price'] = df['can_price'].replace('', np.nan)
df['Extended Retail'] = df['Extended Retail'].replace('', np.nan)
df['Extended @ 3%'] = df['Extended @ 3%'].replace('', np.nan)

# Convertir las columnas de precios a float, asegurándonos de que los valores no numéricos se conviertan a NaN
df['us_price'] = pd.to_numeric(df['us_price'], errors='coerce')
df['can_price'] = pd.to_numeric(df['can_price'], errors='coerce')
df['Extended Retail'] = pd.to_numeric(df['Extended Retail'], errors='coerce')
df['Extended @ 3%'] = pd.to_numeric(df['Extended @ 3%'], errors='coerce')

# Convertir la columna 'pub_date' a formato de fecha
df['pub_date'] = pd.to_datetime(df['pub_date'], format='%d/%m/%Y %H:%M')

# Reemplazar NaN por None (NULL en base de datos)
df = df.where(pd.notna(df), None)

# Guardar el archivo CSV limpio
df.to_csv("archivo_limpio.csv", index=False)

print("Archivo limpio guardado como 'archivo_limpio.csv'")
