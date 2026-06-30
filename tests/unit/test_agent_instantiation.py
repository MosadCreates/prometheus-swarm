"""Test that all six agent classes can be instantiated without error."""

import sys

sys.path.insert(0, ".")


from agents.scout.agent import ScoutAgent
from agents.forge.agent import ForgeAgent
from agents.furnace.agent import FurnaceAgent
from agents.dissect.agent import DissectAgent
from agents.arbiter.agent import ArbiterAgent
from agents.harbor.agent import HarborAgent


def test_scout_agent_instantiation():
    agent = ScoutAgent(job_id="test-instantiation")
    assert agent.agent_name == "Scout"


def test_forge_agent_instantiation():
    agent = ForgeAgent(job_id="test-instantiation")
    assert agent.agent_name == "Forge"


def test_furnace_agent_instantiation():
    agent = FurnaceAgent(job_id="test-instantiation")
    assert agent.agent_name == "Furnace"


def test_dissect_agent_instantiation():
    agent = DissectAgent(job_id="test-instantiation")
    assert agent.agent_name == "Dissect"


def test_arbiter_agent_instantiation():
    agent = ArbiterAgent(job_id="test-instantiation")
    assert agent.agent_name == "Arbiter"


def test_harbor_agent_instantiation():
    agent = HarborAgent(job_id="test-instantiation")
    assert agent.agent_name == "Harbor"


def test_all_agents_instantiate():
    agents = [
        ScoutAgent(job_id="test-instantiation"),
        ForgeAgent(job_id="test-instantiation"),
        FurnaceAgent(job_id="test-instantiation"),
        DissectAgent(job_id="test-instantiation"),
        ArbiterAgent(job_id="test-instantiation"),
        HarborAgent(job_id="test-instantiation"),
    ]
    names = [a.agent_name for a in agents]
    assert names == ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]
