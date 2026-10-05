"""ANA-1 output contract, validated before any result is persisted."""
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class NarrativeResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=1, max_length=8000)
    archetype: str = Field(min_length=1, max_length=500)
    win_conditions: list[str] = Field(max_length=30)
    synergies: list[str] = Field(max_length=50)
    cohesion_score: StrictInt = Field(ge=0, le=100)
    issues: list[str] = Field(max_length=50)
    recommendations: list[str] = Field(max_length=50)
