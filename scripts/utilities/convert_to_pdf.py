#!/usr/bin/env python3
"""Convertit le guide Markdown en PDF avec style professionnel."""

import markdown
from weasyprint import HTML, CSS
from pathlib import Path

def convert_markdown_to_pdf():
    """Convertit le guide d'utilisation Markdown en PDF stylé."""
    
    # Fichiers source et destination
    markdown_file = Path("Guide_Utilisation_36TB_Intelligence.md")
    html_file = Path("Guide_Utilisation_36TB_Intelligence.html")
    pdf_file = Path("Guide_Utilisation_36TB_Intelligence.pdf")
    
    print(f"🔄 Lecture du fichier Markdown: {markdown_file}")
    
    # Lire le contenu Markdown
    with open(markdown_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    print("🔄 Conversion Markdown → HTML...")
    
    # Convertir Markdown en HTML
    md = markdown.Markdown(extensions=[
        'toc',           # Table des matières
        'codehilite',    # Coloration syntaxique
        'fenced_code',   # Code fences
        'tables',        # Tableaux
        'attr_list',     # Attributs
        'def_list',      # Listes de définitions
        'footnotes',     # Notes de bas de page
        'md_in_html',    # Markdown dans HTML
    ])
    
    html_content = md.convert(markdown_content)
    
    # Template HTML complet avec style professionnel
    full_html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Guide d'Utilisation - 36TB Intelligence</title>
        <style>
        /* Style professionnel pour PDF */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #2d3748;
            max-width: none;
            margin: 0;
            padding: 0;
            background: white;
        }}
        
        /* En-têtes */
        h1 {{
            color: #1a202c;
            font-size: 24pt;
            font-weight: 700;
            margin-top: 2em;
            margin-bottom: 1em;
            border-bottom: 3px solid #667eea;
            padding-bottom: 0.5em;
        }}
        
        h2 {{
            color: #2d3748;
            font-size: 18pt;
            font-weight: 600;
            margin-top: 1.8em;
            margin-bottom: 0.8em;
            border-left: 4px solid #667eea;
            padding-left: 1em;
        }}
        
        h3 {{
            color: #4a5568;
            font-size: 14pt;
            font-weight: 600;
            margin-top: 1.5em;
            margin-bottom: 0.6em;
        }}
        
        h4 {{
            color: #718096;
            font-size: 12pt;
            font-weight: 600;
            margin-top: 1.2em;
            margin-bottom: 0.5em;
        }}
        
        /* Paragraphes et listes */
        p {{
            margin-bottom: 1em;
            text-align: justify;
        }}
        
        ul, ol {{
            margin-bottom: 1em;
            padding-left: 1.5em;
        }}
        
        li {{
            margin-bottom: 0.3em;
        }}
        
        /* Code */
        code {{
            font-family: 'JetBrains Mono', 'Consolas', monospace;
            background-color: #f7fafc;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-size: 9pt;
            border: 1px solid #e2e8f0;
        }}
        
        pre {{
            background-color: #1a202c;
            color: #e2e8f0;
            padding: 1em;
            border-radius: 6px;
            overflow-x: auto;
            font-family: 'JetBrains Mono', monospace;
            font-size: 9pt;
            line-height: 1.4;
            margin: 1em 0;
        }}
        
        pre code {{
            background: transparent;
            border: none;
            padding: 0;
            color: inherit;
        }}
        
        /* Tableaux */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1em 0;
            font-size: 10pt;
        }}
        
        th, td {{
            border: 1px solid #e2e8f0;
            padding: 0.5em;
            text-align: left;
        }}
        
        th {{
            background-color: #f7fafc;
            font-weight: 600;
            color: #2d3748;
        }}
        
        tr:nth-child(even) {{
            background-color: #fafafa;
        }}
        
        /* Liens */
        a {{
            color: #667eea;
            text-decoration: none;
        }}
        
        a:hover {{
            text-decoration: underline;
        }}
        
        /* Blockquotes */
        blockquote {{
            border-left: 4px solid #667eea;
            padding-left: 1em;
            margin: 1em 0;
            font-style: italic;
            background-color: #f7fafc;
            padding: 1em;
            border-radius: 0 6px 6px 0;
        }}
        
        /* Page breaks */
        .page-break {{
            page-break-before: always;
        }}
        
        /* Header/Footer pour PDF */
        @page {{
            size: A4;
            margin: 2cm;
            
            @top-left {{
                content: "36TB Intelligence - Guide d'Utilisation";
                font-size: 9pt;
                color: #718096;
            }}
            
            @top-right {{
                content: "Version 1.0 - Sept. 2025";
                font-size: 9pt;
                color: #718096;
            }}
            
            @bottom-center {{
                content: "Page " counter(page) " sur " counter(pages);
                font-size: 9pt;
                color: #718096;
            }}
        }}
        
        /* Table des matières */
        .toc {{
            background-color: #f7fafc;
            padding: 1.5em;
            border-radius: 8px;
            margin: 2em 0;
            border: 1px solid #e2e8f0;
        }}
        
        .toc ul {{
            list-style-type: none;
            padding-left: 0;
        }}
        
        .toc li {{
            margin-bottom: 0.5em;
        }}
        
        .toc a {{
            color: #4a5568;
            text-decoration: none;
            font-weight: 500;
        }}
        
        .toc a:hover {{
            color: #667eea;
        }}
        
        /* Badges et étiquettes */
        .badge {{
            display: inline-block;
            padding: 0.2em 0.6em;
            border-radius: 12px;
            font-size: 9pt;
            font-weight: 600;
            background-color: #667eea;
            color: white;
        }}
        
        /* Sections spéciales */
        .warning {{
            background-color: #fff5f5;
            border: 1px solid #fc8181;
            border-radius: 6px;
            padding: 1em;
            margin: 1em 0;
        }}
        
        .info {{
            background-color: #f0fff4;
            border: 1px solid #68d391;
            border-radius: 6px;
            padding: 1em;
            margin: 1em 0;
        }}
        
        .note {{
            background-color: #fffaf0;
            border: 1px solid #f6ad55;
            border-radius: 6px;
            padding: 1em;
            margin: 1em 0;
        }}
        
        /* Responsive pour écrans */
        @media screen and (max-width: 768px) {{
            body {{
                padding: 1em;
            }}
            
            h1 {{
                font-size: 20pt;
            }}
            
            h2 {{
                font-size: 16pt;
            }}
        }}
        </style>
    </head>
    <body>
        <div class="toc">
            {md.toc if hasattr(md, 'toc') else ''}
        </div>
        {html_content}
    </body>
    </html>
    """
    
    print("🔄 Écriture du fichier HTML temporaire...")
    
    # Sauvegarder le HTML temporaire
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(full_html)
    
    print("🔄 Conversion HTML → PDF...")
    
    # Convertir HTML en PDF
    try:
        # CSS supplémentaire pour WeasyPrint
        css = CSS(string="""
        @page {
            size: A4;
            margin: 2cm;
        }
        
        body {
            font-size: 10pt;
        }
        
        .page-break {
            page-break-before: always;
        }
        """)
        
        html_doc = HTML(filename=str(html_file))
        html_doc.write_pdf(str(pdf_file), stylesheets=[css])
        
        print(f"✅ PDF généré avec succès: {pdf_file}")
        print(f"📄 Taille: {pdf_file.stat().st_size / (1024*1024):.1f} MB")
        
        # Nettoyer le fichier HTML temporaire
        html_file.unlink()
        print("🧹 Fichier HTML temporaire supprimé")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la conversion PDF: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Conversion du Guide d'Utilisation Markdown → PDF")
    print("=" * 60)
    
    success = convert_markdown_to_pdf()
    
    if success:
        print("\n🎉 Conversion terminée avec succès!")
        print("📖 Votre guide PDF est prêt à être consulté.")
    else:
        print("\n❌ Échec de la conversion")
        print("Vérifiez les erreurs ci-dessus.")