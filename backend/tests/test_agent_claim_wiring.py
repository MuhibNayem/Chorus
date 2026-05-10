import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.agents import AGENT_SYSTEM_PROMPTS, AgentSwarm, build_agent_toolset


def make_tools():
    all_tools = [
        "write_file",
        "read_file",
        "list_files",
        "execute_command",
        "create_directory",
        "delete_file",
    ]
    extras = {
        "create_project_zip": "create_project_zip",
        "upload_project_to_storage": "upload_project_to_storage",
        "get_project_download_url": "get_project_download_url",
        "delete_backend_directory": "delete_backend_directory",
        "delete_frontend_directory": "delete_frontend_directory",
        "write_todos": "write_todos",
        "update_todo_status": "update_todo_status",
        "publish_claim": "publish_claim",
        "wait_for_claim": "wait_for_claim",
        "verify_and_publish_claim": "verify_and_publish_claim",
        "verify_progress": "verify_progress",
        "web_search": "web_search",
        "fetch_url": "fetch_url",
        "ask_user": "ask_user",
        "write_spec_file": "write_spec_file",
        "poll_user_directive": "poll_user_directive",
        "verify_contract": "verify_contract",
    }
    return all_tools, extras


def toolset(agent_name):
    all_tools, extras = make_tools()
    return build_agent_toolset(agent_name, all_tools, **extras)


def test_backend_toolset_has_claim_tools_without_coordinator_validators():
    tools = toolset("backend")

    assert "publish_claim" in tools
    assert "wait_for_claim" in tools
    assert "verify_progress" in tools
    assert "verify_and_publish_claim" in tools
    assert "validate_claim" not in tools
    assert "revoke_claim" not in tools


def test_frontend_toolset_uses_claim_wait_not_legacy_wait_on_agent():
    tools = toolset("frontend")

    assert "wait_for_claim" in tools
    assert "publish_claim" in tools
    assert "verify_progress" in tools
    assert "verify_and_publish_claim" in tools
    assert "wait_on_agent" not in tools


def test_devops_and_packager_toolsets_include_claim_wait_and_publish():
    for agent_name in ("devops", "packager"):
        tools = toolset(agent_name)
        assert "wait_for_claim" in tools
        assert "publish_claim" in tools
        assert "verify_and_publish_claim" in tools


def test_rootdep_prompt_publishes_spec_ready_without_code_generation():
    prompt = AGENT_SYSTEM_PROMPTS["rootdep"]

    assert 'publish_claim("SPEC_READY"' in prompt
    assert "Do NOT generate any application code" in prompt
    assert "Do NOT call generate_spring_boot_project" in prompt


def test_backend_prompt_waits_for_spec_and_publishes_backend_claims():
    prompt = AGENT_SYSTEM_PROMPTS["backend"]

    assert 'wait_for_claim("SPEC_READY")' in prompt
    assert "verify_progress" in prompt
    assert 'verify_and_publish_claim("BACKEND_RUNTIME_READY"' in prompt
    assert 'verify_and_publish_claim("BACKEND_API_READY"' in prompt
    assert "signal_ready" not in prompt
    assert "Dockerfile" in prompt
    assert "DevOps owns all deployment artifacts" in prompt


def test_frontend_prompt_waits_for_spec_and_backend_api_claims():
    prompt = AGENT_SYSTEM_PROMPTS["frontend"]

    assert 'wait_for_claim("SPEC_READY")' in prompt
    assert 'wait_for_claim("BACKEND_API_READY")' in prompt
    assert "verify_progress" in prompt
    assert 'verify_and_publish_claim("FRONTEND_SOURCE_READY"' in prompt
    assert 'verify_and_publish_claim("FRONTEND_BUILD_READY"' in prompt
    assert "wait_on_agent" not in prompt
    assert "DevOps owns all deployment artifacts" in prompt


def test_devops_prompt_waits_for_app_claims_and_owns_deployment():
    prompt = AGENT_SYSTEM_PROMPTS["devops"]

    assert 'wait_for_claim("BACKEND_RUNTIME_READY")' in prompt
    assert 'wait_for_claim("FRONTEND_BUILD_READY")' in prompt
    assert 'verify_and_publish_claim("DEPLOYMENT_READY"' in prompt
    assert "Derive versions from real manifests" in prompt
    assert "You are the owner of Dockerfiles" in prompt


def test_packager_prompt_waits_for_deployment_and_publishes_package_claim():
    prompt = AGENT_SYSTEM_PROMPTS["packager"]

    assert 'wait_for_claim("DEPLOYMENT_READY")' in prompt
    assert 'publish_claim("PACKAGE_READY"' in prompt
    assert "Do NOT generate app code or deployment code" in prompt


def test_modify_mode_backend_prompt_uses_claim_language_not_legacy_signal():
    prompt = AgentSwarm()._prompt_for_mode("backend", AGENT_SYSTEM_PROMPTS["backend"])

    assert "BACKEND_RUNTIME_READY" in prompt
    assert "BACKEND_API_READY" in prompt
    assert "signal_ready" not in prompt
