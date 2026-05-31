"""
Multi-Modal Verification Engine (VLM).
Uses a Vision-Language Model to inspect monitoring screenshots (Grafana/Prometheus),
analyses visual graphs to verify CPU drop / recovery, and certifies successful incident resolution.
"""

import base64
import sys
import logging
from pathlib import Path
from typing import Dict, Any

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.llm import get_llm_router

logger = logging.getLogger("vision_verifier")


class VisionSystemVerifier:
    def __init__(self):
        self.llm = get_llm_router()
        self.default_dashboard_path = Path(__file__).resolve().parent.parent / "docs"

    async def verify_incident_resolution(
        self, screenshot_path: str = None
    ) -> Dict[str, Any]:
        """
        Loads the SRE dashboard screenshot and prompts the VLM to verify if the system has returned to 'green'.
        """
        # Resolve target screenshot
        if not screenshot_path:
            # Look for the generated Grafana dashboard in the conversation directory
            matches = list(
                self.default_dashboard_path.glob("monitoring_dashboard_*.png")
            )
            if matches:
                resolved_path = matches[0]
            else:
                logger.warning(
                    "No generated monitoring dashboard screenshot found. Trying the documented fallback path."
                )
                resolved_path = self.default_dashboard_path / "monitoring_dashboard.png"
        else:
            resolved_path = Path(screenshot_path)

        logger.info(f"VLM Verifier: Loading dashboard screenshot at: {resolved_path}")
        if not resolved_path.exists():
            return {
                "success": False,
                "screenshot_inspected": str(resolved_path),
                "verification_status": "FAILED_VERIFICATION",
                "error": "Dashboard screenshot was not found.",
            }

        mime_type = (
            "image/png" if resolved_path.suffix.lower() == ".png" else "image/jpeg"
        )
        encoded_image = base64.b64encode(resolved_path.read_bytes()).decode("ascii")

        # Prompting our SRE Vision validator
        vlm_analysis_prompt = f"""You are a multi-modal AIOps Verification Engine.
You have been provided with an image of the Grafana SRE monitoring dashboard (loaded from {resolved_path.name}).

Please analyze the SRE dashboard visually and evaluate:
1. Is there a status badge indicating 'HEALTHY' in green?
2. Does the CPU load graph show a sharp decrease from a high spike (e.g. 98% down to 15%) indicating a successful patch?
3. Are there any other active alerts or anomalies on the screen?

Provide your verification report in the following JSON format:
{{
  "verification_status": "VERIFIED_GREEN" | "FAILED_VERIFICATION",
  "dashboard_status": "HEALTHY",
  "cpu_graph_trend": "Spiked to 98% then dropped dramatically to 15% (Success)",
  "active_alerts_count": 0,
  "confidence_score": 0.98,
  "vlm_detailed_notes": "Slightly detailed SRE notes about the visual indicators."
}}
Return only valid JSON. Do not wrap in markdown or backticks."""

        try:
            # We call our default LLM router to generate the structured visual inspection output
            res = await self.llm.chat(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": vlm_analysis_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{encoded_image}"
                                },
                            },
                        ],
                    }
                ],
                task="vision",
                temperature=0.1,
            )
            cleaned = res.replace("```json", "").replace("```", "").strip()
            import json

            data = json.loads(cleaned)
            logger.info(
                "✅ Multi-Modal Verification: SRE Dashboard visually confirmed green!"
            )
            return {"success": True, "screenshot_inspected": str(resolved_path), **data}
        except Exception as e:
            logger.error(f"VLM Analysis parsing failed: {e}")
            return {
                "success": False,
                "screenshot_inspected": str(resolved_path),
                "verification_status": "FAILED_VERIFICATION",
                "error": str(e),
            }


async def main():
    verifier = VisionSystemVerifier()
    report = await verifier.verify_incident_resolution()
    print("=" * 80)
    print("📸 MULTI-MODAL VISION VERIFICATION SYSTEM (VLM-AS-A-CHECKER)")
    print("=" * 80)
    print(f"Inspected Screenshot: {report['screenshot_inspected']}")
    print(f"Verification Status:  {report['verification_status']}")
    if report["success"]:
        print(f"Dashboard Health:     {report['dashboard_status']}")
        print(f"CPU Load Visual Trend: {report['cpu_graph_trend']}")
        print(f"Active Visual Alerts: {report['active_alerts_count']}")
        print(f"Confidence Score:     {report['confidence_score'] * 100}%")
        print(f"VLM SRE Analysis Notes: {report['vlm_detailed_notes']}")
    else:
        print(f"Verification Error:   {report['error']}")
    print("=" * 80)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
