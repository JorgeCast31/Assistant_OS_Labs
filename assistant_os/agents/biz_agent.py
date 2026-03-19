"""
BizAgent - Simula análisis de negocio: estrategia, riesgos, pasos accionables.
Usa contratos Request/Response.
"""
from ..contracts import Request, Response, make_ok


class BizAgent:
    """Agente para análisis de negocio (stub)."""
    
    def run(self, req: Request) -> Response:
        """
        Simula análisis de negocio.
        
        Args:
            req: Request con payload.task
        
        Returns:
            Response estructurada
        """
        task = req["payload"].get("task", req["payload"].get("raw", ""))
        context_id = req["context_id"]
        
        return make_ok(
            agent="biz",
            context_id=context_id,
            output={
                "next_actions": [
                    {
                        "step": 1,
                        "title": "Validar problema-solución",
                        "description": "Entrevistar a 10 clientes potenciales",
                        "timeline": "2 semanas",
                    },
                    {
                        "step": 2,
                        "title": "MVP mínimo",
                        "description": "Construir prototipo funcional con 3 features core",
                        "timeline": "4 semanas",
                    },
                    {
                        "step": 3,
                        "title": "Pricing inicial",
                        "description": "Definir modelo de precios basado en valor",
                        "timeline": "1 semana",
                    },
                ],
                "risks": [
                    {
                        "risk": "Competencia establecida",
                        "severity": "alta",
                        "mitigation": "Diferenciarse en nicho específico",
                    },
                    {
                        "risk": "Tiempo al mercado",
                        "severity": "media",
                        "mitigation": "Lanzar beta cerrada en 6 semanas",
                    },
                ],
                "topic": task,
            },
        )
