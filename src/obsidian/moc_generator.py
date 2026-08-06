"""
Map of Content (MOC) generator for Obsidian vault.
"""
from pathlib import Path
import structlog

from src.obsidian.config_obsidian import VAULT_DIR, INDUSTRY_MAP, MOC_TEMPLATE, DASHBOARD_TEMPLATE
from src.config import BUSINESS_FIELDS

logger = structlog.get_logger(__name__)

def generate_field_mocs(vault_dir: Path = VAULT_DIR) -> None:
    """Generate MOC pages for each legal field."""
    mocs_dir = vault_dir / "MOCs" / "Fields"
    mocs_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    for field_id, field_name in BUSINESS_FIELDS.items():
        md_content = MOC_TEMPLATE.format(
            category_type="field",
            category_type_vi="lĩnh vực",
            name=field_name,
            category_field="fields"
        )
        
        # Avoid slashes in filenames
        safe_name = field_name.replace("/", "-").replace("\\\\", "-")
        out_path = mocs_dir / f"{safe_name}.md"
        
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        count += 1
            
    logger.info("Generated field MOCs", count=count)

def generate_industry_mocs(vault_dir: Path = VAULT_DIR) -> None:
    """Generate MOC pages for each industry."""
    mocs_dir = vault_dir / "MOCs" / "Industries"
    mocs_dir.mkdir(parents=True, exist_ok=True)
    
    count = 0
    for industry_name in INDUSTRY_MAP.keys():
        md_content = MOC_TEMPLATE.format(
            category_type="industry",
            category_type_vi="ngành nghề",
            name=industry_name,
            category_field="industries"
        )
        
        safe_name = industry_name.replace("/", "-").replace("\\\\", "-")
        out_path = mocs_dir / f"{safe_name}.md"
        
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        count += 1
            
    logger.info("Generated industry MOCs", count=count)

def generate_dashboard(vault_dir: Path = VAULT_DIR) -> None:
    """Generate the main dashboard page."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    out_path = vault_dir / "00_Dashboard.md"
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(DASHBOARD_TEMPLATE)
        
    logger.info("Generated Dashboard")

def generate_all_mocs(vault_dir: Path = VAULT_DIR) -> None:
    """Generate all MOCs and Dashboard."""
    generate_field_mocs(vault_dir)
    generate_industry_mocs(vault_dir)
    generate_dashboard(vault_dir)
    
if __name__ == "__main__":
    generate_all_mocs()
