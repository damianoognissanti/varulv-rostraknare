Sidan finns på:
https://damianoognissanti.github.io/varulv-rostraknare/

## Köra lokalt
1) Klona/ladda ner repot  
2) Starta en lokal webbserver i repo-roten:
```bash
python -m http.server 8000
```
3) Öppna i webbläsaren: http://localhost:8000/

## Uppdatera datat (valfritt)
Hämta/synka trådar till `data`:
```bash
python fetch_varulvsspel.py
```
Bygg eller uppdatera archive.json:
```bash
python build_archive.py
```
