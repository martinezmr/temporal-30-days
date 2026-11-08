"""Inputs and outputs that cross workflow/activity boundaries. Day 3 onward: no bare dicts."""

from datetime import datetime

from pydantic import BaseModel


class FactsRequest(BaseModel):
    """Input to GetFactsWorkflow and get_device_facts.

    One model instead of positional arguments, so a field can be added later without
    breaking workflows that are already running.
    """

    device: str


class DeviceFacts(BaseModel):
    device: str
    model: str
    version: str


class FactsReport(BaseModel):
    facts: DeviceFacts
    collected_at: datetime


class ShowTechRequest(BaseModel):
    device: str


class ShowTechResult(BaseModel):
    """Where the outputs were written. The outputs themselves stay out of workflow history."""

    device: str
    output_dir: str
    commands_collected: int
    resumed_from: int
