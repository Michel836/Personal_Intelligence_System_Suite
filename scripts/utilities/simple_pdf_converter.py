#!/usr/bin/env python3
"""Conversion simple Markdown vers PDF en utilisant les outils disponibles."""

import markdown
from pathlib import Path
import platform

def create_styled_html(markdown_content, title="Guide d'Utilisation 36TB Intelligence"):
    """Crée un HTML stylé à partir du contenu Markdown."""
    
    # Convertir Markdown en HTML
    md = markdown.Markdown(extensions=[
        'toc',
        'codehilite', 
        'fenced_code',
        'tables',
    ])
    
    html_body = md.convert(markdown_content)
    
    # Template HTML avec style intégré
    styled_html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                background: white;
            }}
            
            h1 {{
                color: #1e3a8a;
                border-bottom: 3px solid #3b82f6;
                padding-bottom: 10px;
                font-size: 2.5em;
                margin-top: 30px;
            }}
            
            h2 {{
                color: #1e40af;
                border-left: 4px solid #3b82f6;
                padding-left: 15px;
                font-size: 1.8em;
                margin-top: 25px;
            }}
            
            h3 {{
                color: #1e40af;
                font-size: 1.4em;
                margin-top: 20px;
            }}
            
            h4 {{
                color: #374151;
                font-size: 1.2em;
                margin-top: 18px;
            }}
            
            code {{
                background-color: #f3f4f6;
                padding: 2px 4px;
                border-radius: 3px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 0.9em;
                border: 1px solid #d1d5db;
            }}
            
            pre {{
                background-color: #1f2937;
                color: #f9fafb;
                padding: 15px;
                border-radius: 5px;
                overflow-x: auto;
                font-family: 'Consolas', 'Monaco', monospace;
                margin: 15px 0;
            }}
            
            pre code {{
                background: transparent;
                border: none;
                color: inherit;
            }}
            
            blockquote {{
                border-left: 4px solid #3b82f6;
                margin: 15px 0;
                padding: 10px 20px;
                background-color: #f8fafc;
                border-radius: 0 5px 5px 0;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
            }}
            
            th, td {{
                border: 1px solid #d1d5db;
                padding: 8px 12px;
                text-align: left;
            }}
            
            th {{
                background-color: #f3f4f6;
                font-weight: bold;
            }}
            
            tr:nth-child(even) {{
                background-color: #f9fafb;
            }}
            
            ul, ol {{
                margin: 10px 0;
                padding-left: 25px;
            }}
            
            li {{
                margin: 5px 0;
            }}
            
            a {{
                color: #3b82f6;
                text-decoration: none;
            }}
            
            a:hover {{
                text-decoration: underline;
            }}
            
            .toc {{
                background-color: #f8fafc;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }}
            
            .toc ul {{
                list-style-type: none;
                padding-left: 0;
            }}
            
            .toc li {{
                margin: 8px 0;
            }}
            
            .cover-page {{
                text-align: center;
                padding: 50px 0;
                page-break-after: always;
            }}
            
            .cover-title {{
                font-size: 3em;
                color: #1e3a8a;
                margin-bottom: 20px;
            }}
            
            .cover-subtitle {{
                font-size: 1.5em;
                color: #6b7280;
                margin-bottom: 30px;
            }}
            
            .cover-info {{
                font-size: 1.2em;
                color: #374151;
                line-height: 1.8;
            }}
            
            @media print {{
                body {{
                    margin: 0;
                    padding: 15px;
                }}
                
                .page-break {{
                    page-break-before: always;
                }}
                
                a {{
                    color: #333 !important;
                    text-decoration: none !important;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="cover-page">
            <h1 class="cover-title">📖 Guide d'Utilisation</h1>
            <h2 class="cover-subtitle">36TB Intelligence</h2>
            <div class="cover-info">
                <p><strong>Système d'Exploitation de Connaissances Personnelles</strong></p>
                <p><strong>avec Témoins Visuels d'Activité Temps Réel</strong></p>
                <br>
                <p>Version 1.0 - Septembre 2025</p>
                <p>Développé avec ❤️ pour démocratiser l'IA personnelle</p>
            </div>
        </div>
        
        <div class="page-break"></div>
        
        {html_body}
        
        <div class="page-break"></div>
        
        <div style="text-align: center; padding: 30px; color: #6b7280;">
            <h2>📞 Support et Ressources</h2>
            <p><strong>Launcher Principal:</strong> http://localhost:8504</p>
            <p><strong>Interface Classique:</strong> http://localhost:8501</p>
            <p><strong>Interface Moderne:</strong> http://localhost:8503</p>
            <br>
            <p><strong>Commande de lancement:</strong></p>
            <code>.venv/Scripts/python.exe -m streamlit run launcher.py</code>
            <br><br>
            <p>© 2025 - 36TB Intelligence Project</p>
            <p>Guide généré automatiquement avec témoins visuels intégrés</p>
        </div>
    </body>
    </html>
    """
    
    return styled_html

def convert_to_pdf():
    """Conversion principale du guide."""
    
    markdown_file = Path("Guide_Utilisation_36TB_Intelligence.md")
    html_file = Path("Guide_Utilisation_36TB_Intelligence.html")
    
    print(f"Lecture du fichier Markdown: {markdown_file}")
    
    if not markdown_file.exists():
        print(f"Fichier non trouve: {markdown_file}")
        return False
    
    # Lire le contenu Markdown
    with open(markdown_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    print("Conversion Markdown -> HTML style...")
    
    # Créer le HTML stylé
    styled_html = create_styled_html(markdown_content)
    
    # Sauvegarder le HTML
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(styled_html)
    
    print(f"Fichier HTML cree: {html_file}")
    print(f"Taille: {html_file.stat().st_size / 1024:.1f} KB")
    
    # Instructions pour conversion PDF
    print("\n" + "="*60)
    print("FICHIER HTML GENERE AVEC SUCCES!")
    print("="*60)
    print(f"Fichier: {html_file.absolute()}")
    print("\nPour convertir en PDF, vous avez plusieurs options:")
    print("\n1. Via navigateur web (Recommande):")
    print(f"   - Ouvrir: file:///{html_file.absolute()}")
    print("   - Ctrl+P -> Imprimer -> Enregistrer au format PDF")
    print("   - Selectionner 'Plus de parametres' -> Cocher 'Graphiques d'arriere-plan'")
    
    print("\n2. Via Chrome en ligne de commande:")
    chrome_paths = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome"
    ]
    
    chrome_path = None
    for path in chrome_paths:
        if Path(path).exists():
            chrome_path = path
            break
    
    if chrome_path:
        cmd = f'"{chrome_path}" --headless --disable-gpu --print-to-pdf="Guide_Utilisation_36TB_Intelligence.pdf" "file:///{html_file.absolute()}"'
        print(f"   {cmd}")
    else:
        print("   Chrome non trouve automatiquement")
    
    print("\n3. Outils en ligne:")
    print("   - https://www.ilovepdf.com/html-to-pdf")
    print("   - https://pdfcrowd.com/html-to-pdf/")
    
    print("\nLe fichier HTML est optimise pour l'impression PDF avec:")
    print("   - Style professionnel")
    print("   - Page de couverture") 
    print("   - Table des matieres")
    print("   - Code colore")
    print("   - Tableaux formates")
    print("   - URLs et references")
    
    return True

if __name__ == "__main__":
    print("Generation du Guide d'Utilisation 36TB Intelligence")
    print("Markdown -> HTML -> PDF")
    print("=" * 60)
    
    success = convert_to_pdf()
    
    if success:
        print("\nGeneration HTML terminee avec succes!")
        print("Suivez les instructions ci-dessus pour creer le PDF final.")
    else:
        print("\nEchec de la generation")