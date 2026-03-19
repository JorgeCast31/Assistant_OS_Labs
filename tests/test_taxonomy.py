"""
Tests for taxonomy module - Domain/Proyecto/Project Key classification.

Run with: python -m unittest tests.test_taxonomy -v
"""
import unittest
from assistant_os.taxonomy import (
    parse_target_from_text,
    build_target_filter,
    infer_taxonomy,
    ParsedTarget,
    InferredTaxonomy,
)


class TestParseTargetFromText:
    """Test target parsing from user input."""
    
    def test_explicit_key_prefix(self):
        """Test key: prefix parsing."""
        result = parse_target_from_text("tareas key:thcye")
        assert result["target_type"] == "key"
        assert result["value"] == "thcye"
    
    def test_explicit_domain_prefix(self):
        """Test domain: prefix parsing."""
        result = parse_target_from_text("tareas domain:Tesis")
        assert result["target_type"] == "domain"
        assert result["value"] == "Tesis"
    
    def test_explicit_project_prefix(self):
        """Test proyecto: prefix parsing."""
        result = parse_target_from_text("tareas proyecto:THCyE")
        assert result["target_type"] == "project"
        assert result["value"] == "THCyE"
    
    def test_exact_proyecto_match(self):
        """Test exact match against Proyecto options (via alias->key)."""
        result = parse_target_from_text("tareas de THCyE")
        # THCyE alias maps to key "thcye" for ProjectKey filtering
        assert result["target_type"] == "key"
        assert result["value"] == "thcye"
    
    def test_exact_proyecto_match_cultura_cadenas(self):
        """Test exact match for Cultura de Cadenas (via alias->key)."""
        result = parse_target_from_text("tareas Cultura de Cadenas")
        # Cultura de Cadenas alias maps to key for ProjectKey filtering
        assert result["target_type"] == "key"
        assert result["value"] == "cultura_de_cadenas"
    
    def test_alias_thcye(self):
        """Test alias resolution for thcye -> key filtering."""
        result = parse_target_from_text("tareas thcye")
        assert result["target_type"] == "key"
        assert result["value"] == "thcye"
    
    def test_alias_tesis(self):
        """Test alias resolution for tesis."""
        result = parse_target_from_text("tareas tesis")
        assert result["target_type"] == "domain"
        assert result["value"] == "Tesis"
    
    def test_alias_busqueda_laboral(self):
        """Test alias resolution for busqueda laboral."""
        result = parse_target_from_text("tareas busqueda laboral")
        assert result["target_type"] == "project"
        assert result["value"] == "Búsqueda laboral"
    
    def test_alias_tti(self):
        """Test alias resolution for TTI -> key filtering."""
        result = parse_target_from_text("tareas tti")
        assert result["target_type"] == "key"
        assert result["value"] == "tti_eco"
    
    def test_alias_eiprota(self):
        """Test alias resolution for eiprota -> key filtering."""
        result = parse_target_from_text("tareas eiprota")
        assert result["target_type"] == "key"
        assert result["value"] == "eiprota"
    
    def test_alias_cadenas(self):
        """Test alias resolution for cadenas."""
        result = parse_target_from_text("tareas cadenas")
        assert result["target_type"] == "project"
        assert result["value"] == "Cultura de Cadenas"
    
    def test_no_target(self):
        """Test no target found."""
        result = parse_target_from_text("tareas urgentes")
        # Could be "keyword" with "urgentes" or "none"
        assert result["target_type"] in ("none", "keyword")
    
    def test_status_only(self):
        """Test status queries don't get misclassified."""
        result = parse_target_from_text("tareas NEXT")
        # NEXT is a status, should not be picked up as project
        assert result["target_type"] == "none" or result["value"] not in ["NEXT", "INBOX", "WAITING"]


class TestBuildTargetFilter:
    """Test filter building from parsed targets."""
    
    def test_key_filter(self):
        """Test Project Key filter building."""
        parsed = ParsedTarget(target_type="key", value="thcye", raw_text="tareas key:thcye", has_explicit_prefix=True)
        result = build_target_filter(parsed)
        
        assert result["filter_type"] == "key"
        assert result["property_name"] == "Project Key"
        assert result["filter_op"] == "equals"
        assert result["filter_value"] == "thcye"
    
    def test_project_filter(self):
        """Test Proyecto filter building."""
        parsed = ParsedTarget(target_type="project", value="THCyE", raw_text="tareas THCyE", has_explicit_prefix=False)
        result = build_target_filter(parsed)
        
        assert result["filter_type"] == "proyecto"
        assert result["property_name"] == "Proyecto"
        assert result["filter_op"] == "contains"
        assert result["filter_value"] == "THCyE"
    
    def test_domain_filter(self):
        """Test Domain filter building.
        
        Note: Domain is a 'select' type in Notion, so uses 'equals' operator.
        """
        parsed = ParsedTarget(target_type="domain", value="Tesis", raw_text="tareas tesis", has_explicit_prefix=False)
        result = build_target_filter(parsed)
        
        assert result["filter_type"] == "domain"
        assert result["property_name"] == "Domain"
        assert result["filter_op"] == "equals"  # Domain is select type, uses equals
        assert result["filter_value"] == "Tesis"
    
    def test_keyword_filter(self):
        """Test title keyword filter building."""
        parsed = ParsedTarget(target_type="keyword", value="CELLAB", raw_text="tareas CELLAB", has_explicit_prefix=False)
        result = build_target_filter(parsed)
        
        assert result["filter_type"] == "title_keyword"
        assert result["property_name"] == "Name"
        assert result["filter_op"] == "contains"
    
    def test_none_filter(self):
        """Test no filter."""
        parsed = ParsedTarget(target_type="none", value="", raw_text="tareas", has_explicit_prefix=False)
        result = build_target_filter(parsed)
        
        assert result["filter_type"] == "none"


class TestInferTaxonomy:
    """Test taxonomy inference."""
    
    def test_thcye_infers_eiprota_domain(self):
        """THCyE project should infer eiProta domain."""
        result = infer_taxonomy(
            title="Revisar THCyE",
            proyecto_list=["THCyE"],
            domain_list=[],
        )
        
        assert "eiProta" in result["domain"]
        assert result["project_key"] == "thcye"
    
    def test_cultura_cadenas_infers_eiprota(self):
        """Cultura de Cadenas should infer eiProta domain."""
        result = infer_taxonomy(
            title="Editar Cultura de Cadenas",
            proyecto_list=["Cultura de Cadenas"],
            domain_list=[],
        )
        
        assert "eiProta" in result["domain"]
        assert result["project_key"] == "cultura_de_cadenas"
    
    def test_tesis_infers_tesis_domain(self):
        """Tesis project should infer Tesis domain."""
        result = infer_taxonomy(
            title="Avanzar tesis",
            proyecto_list=["Tesis"],
            domain_list=[],
        )
        
        assert "Tesis" in result["domain"]
    
    def test_busqueda_laboral_infers_crecimiento_profesional(self):
        """Búsqueda laboral should infer Crecimiento profesional domain."""
        result = infer_taxonomy(
            title="Actualizar CV",
            proyecto_list=["Búsqueda laboral"],
            domain_list=[],
        )
        
        assert "Crecimiento profesional" in result["domain"]
        assert result["project_key"] == "busqueda_laboral"
    
    def test_tti_keyword_in_title_infers_domain(self):
        """TTI keyword in title should infer TTI domain."""
        result = infer_taxonomy(
            title="Revisar documento TTI",
            proyecto_list=[],
            domain_list=[],
        )
        
        assert 'TTI - ECO "…mens oritur"' in result["domain"]
    
    def test_existing_key_not_overwritten(self):
        """Existing project_key should not be overwritten."""
        result = infer_taxonomy(
            title="Nueva tarea",
            proyecto_list=["THCyE"],
            domain_list=[],
            existing_key="custom_key",
        )
        
        assert result["project_key"] == "custom_key"
    
    def test_key_derived_from_proyecto(self):
        """Project key derived from Proyecto if not set."""
        result = infer_taxonomy(
            title="Tarea sin key",
            proyecto_list=["Evangelio III"],
            domain_list=[],
        )
        
        assert result["project_key"] == "evangelio_iii"
    
    def test_multiple_proyectos_infer_multiple_domains(self):
        """Multiple proyectos should infer their respective domains."""
        result = infer_taxonomy(
            title="Cross-project task",
            proyecto_list=["THCyE", "Tesis"],
            domain_list=[],
        )
        
        assert "eiProta" in result["domain"]
        assert "Tesis" in result["domain"]


class TestIntegration:
    """Integration tests for full flow."""
    
    def test_tareas_thcye_full_flow(self):
        """Test 'tareas thcye' -> key filter with thcye slug."""
        parsed = parse_target_from_text("tareas thcye")
        filter_result = build_target_filter(parsed)
        
        assert parsed["target_type"] == "key"
        assert parsed["value"] == "thcye"
        assert filter_result["filter_type"] == "key"
        assert filter_result["filter_value"] == "thcye"
        assert filter_result["property_name"] == "Project Key"
    
    def test_tareas_tesis_full_flow(self):
        """Test 'tareas tesis' -> domain filter with Tesis."""
        parsed = parse_target_from_text("tareas tesis")
        filter_result = build_target_filter(parsed)
        
        assert parsed["target_type"] == "domain"
        assert parsed["value"] == "Tesis"
        assert filter_result["filter_type"] == "domain"
        assert filter_result["filter_value"] == "Tesis"
    
    def test_tareas_busqueda_laboral_full_flow(self):
        """Test 'tareas busqueda laboral' -> project filter."""
        parsed = parse_target_from_text("tareas busqueda laboral")
        filter_result = build_target_filter(parsed)
        
        assert parsed["target_type"] == "project"
        assert parsed["value"] == "Búsqueda laboral"
        assert filter_result["filter_type"] == "proyecto"
    
    def test_tareas_key_explicit(self):
        """Test explicit key:xxx syntax."""
        parsed = parse_target_from_text("tareas key:eda_pt3")
        filter_result = build_target_filter(parsed)
        
        assert parsed["target_type"] == "key"
        assert parsed["value"] == "eda_pt3"
        assert filter_result["filter_type"] == "key"
        assert filter_result["property_name"] == "Project Key"


if __name__ == "__main__":
    unittest.main()
