"""
DocAgent - Simula generación de documentación: outlines, docs, etc.
Usa contratos Request/Response.
"""
import hashlib
import random

from ..contracts import Request, Response, make_ok


class DocAgent:
    """Agente para tareas de documentación (stub)."""
    
    def run(self, req: Request) -> Response:
        """
        Simula la generación de documentación.
        
        Args:
            req: Request con payload.task
        
        Returns:
            Response estructurada
        """
        task = req["payload"].get("task", req["payload"].get("raw", ""))
        context_id = req["context_id"]
        
        # Generar IDs simulados
        doc_id = hashlib.md5(task.encode()).hexdigest()[:8]
        
        return make_ok(
            agent="doc",
            context_id=context_id,
            output={
                "document": {
                    "id": f"SIM-{doc_id.upper()}",
                    "title": task,
                    "format": "markdown",
                    "local_path": f"docs/{task.replace(' ', '_').lower()}.md",
                    "outline": [
                        "1. Introducción",
                        "2. Instalación",
                        "3. Uso básico",
                        "4. API Reference",
                        "5. Ejemplos",
                        "6. Troubleshooting",
                    ],
                    "estimated_pages": random.randint(5, 15),
                    "status": "draft",
                },
            },
        )
