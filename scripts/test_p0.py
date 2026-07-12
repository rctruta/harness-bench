import os
import sys

# Ensure harnessbench is importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from harnessbench.tests.fake_adapter import FakeAdapter
from harnessbench.adapter import SpecialistRole
from harnessbench.runner.specialist import run_specialist

# We must mock litellm.completion to avoid hitting the actual network during the test
import litellm

class MockMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

class MockChoice:
    def __init__(self, message):
        self.message = message

class MockResponse:
    def __init__(self, choices):
        self.choices = choices

# State machine for our mock LLM
call_count = 0
def mock_completion(**kwargs):
    global call_count
    call_count += 1
    
    # Turn 1: Model decides to call echo_tool
    if call_count == 1:
        class MockFunction:
            name = "echo_tool"
            arguments = '{"msg": "hello from the mock"}'
        class MockToolCall:
            id = "call_123"
            function = MockFunction()
            
            def model_dump(self):
                return {
                    "id": self.id,
                    "type": "function",
                    "function": {"name": self.function.name, "arguments": self.function.arguments}
                }
        
        return MockResponse([MockChoice(MockMessage(content="", tool_calls=[MockToolCall()]))])
    
    # Turn 2: Model sees the tool result and returns final answer
    if call_count == 2:
        return MockResponse([MockChoice(MockMessage(content="The echo tool worked!", tool_calls=None))])

litellm.completion = mock_completion

def test_seam():
    adapter = FakeAdapter()
    role = SpecialistRole(
        name="echo_specialist",
        tool_names=["echo_tool"],
        system_prompt="You are a test specialist. Call the echo tool, then return a final answer."
    )
    
    print(f"Testing adapter: {adapter.name}")
    print("Running specialist loop...")
    result = run_specialist(
        adapter=adapter,
        role=role,
        brief="Please run the echo test.",
        model="mock-model",
        runs_dir=os.path.join(_REPO_ROOT, "tests", "runs")
    )
    
    print(f"Specialist result: {result.outcome}")
    print(f"Turns used: {result.turns_used}")
    if result.outcome != "max_turns":
        print("SEAM VERIFIED! run_specialist executed against FakeAdapter without importing SBD.")
    else:
        print("FAILED: Specialist loop did not complete successfully.")
        sys.exit(1)

if __name__ == "__main__":
    test_seam()
