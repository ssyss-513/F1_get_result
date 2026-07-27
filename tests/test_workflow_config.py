import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowConfigTest(unittest.TestCase):
    def test_calendar_sync_requires_dedicated_workflow_token_for_push(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "sync-f1-calendar.yml").read_text(encoding="utf-8")

        self.assertIn("token: ${{ secrets.WORKFLOW_PAT || github.token }}", workflow)
        self.assertIn("WORKFLOW_PAT: ${{ secrets.WORKFLOW_PAT }}", workflow)
        self.assertIn("if: ${{ env.WORKFLOW_PAT != '' }}", workflow)
        self.assertIn("if: ${{ env.WORKFLOW_PAT == '' }}", workflow)

    def test_workflows_use_node_24_actions(self) -> None:
        workflow_dir = ROOT / ".github" / "workflows"
        for path in workflow_dir.glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            self.assertNotIn("actions/checkout@v4", workflow, path.name)
            self.assertNotIn("actions/setup-python@v5", workflow, path.name)

    def test_result_workflow_publishes_before_committing(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "f1-results.yml").read_text(encoding="utf-8")

        publish_position = workflow.index("- name: Publish results to blog")
        commit_position = workflow.index("- name: Commit generated Markdown")
        self.assertLess(publish_position, commit_position)
        self.assertIn("BLOG_PUBLISH_URL: ${{ secrets.BLOG_PUBLISH_URL }}", workflow)
        self.assertIn("BLOG_PUBLISH_SECRET: ${{ secrets.BLOG_PUBLISH_SECRET }}", workflow)


if __name__ == "__main__":
    unittest.main()
