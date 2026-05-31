import logging
import os
import httpx

logger = logging.getLogger(__name__)


class GitHubTool:
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"
        self.headers = (
            {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }
            if self.token
            else {}
        )

    async def create_issue(self, repo: str, title: str, body: str):
        if not self.token:
            logger.warning("GITHUB_TOKEN not found. Using mock implementation.")
            return {
                "success": True,
                "issue_url": f"https://github.com/{repo}/issues/mock-1",
                "status": "mocked",
            }

        logger.info(f"Creating real GitHub issue in {repo}: {title}")
        url = f"{self.base_url}/repos/{repo}/issues"
        payload = {"title": title, "body": body}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers)
            if response.status_code == 201:
                data = response.json()
                return {
                    "success": True,
                    "issue_url": data.get("html_url"),
                    "status": "created",
                }
            else:
                logger.error(f"GitHub API Error: {response.text}")
                return {"success": False, "error": response.text}

    async def create_pr_comment(self, repo: str, pr_number: int, body: str):
        if not self.token:
            logger.warning("GITHUB_TOKEN not found. Using mock implementation.")
            return {"success": True, "status": "mocked"}

        logger.info(f"Adding real comment to PR #{pr_number} in {repo}")
        url = f"{self.base_url}/repos/{repo}/issues/{pr_number}/comments"
        payload = {"body": body}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers)
            if response.status_code == 201:
                return {"success": True, "status": "commented"}
            else:
                return {"success": False, "error": response.text}
