"""Shared conformance suite for extraction models.

Subclass and supply the ``model`` fixture. What every implementation owes the
domain: a string back, and :class:`ModelFailed` — never a vendor-specific
exception — when a call cannot be completed. The domain catches exactly that
type, so a leaked library error would end a whole run instead of costing one
chunk.
"""

from abc import ABC, abstractmethod

import pytest

from phases_v2.extraction.interfaces import ExtractionModel, ModelFailed


class ExtractionModelContract(ABC):
    @pytest.fixture
    @abstractmethod
    def model(self) -> ExtractionModel:
        raise NotImplementedError()

    @pytest.fixture
    @abstractmethod
    def failing_model(self) -> ExtractionModel:
        """The same adapter, wired to something that always errors."""
        raise NotImplementedError()

    def test_it_returns_the_response_as_text(self, model):
        response = model.complete("say something")

        assert isinstance(response, str)
        assert response

    def test_a_transport_error_becomes_model_failed(self, failing_model):
        with pytest.raises(ModelFailed):
            failing_model.complete("say something")

    def test_the_failure_explains_itself(self, failing_model):
        with pytest.raises(ModelFailed) as raised:
            failing_model.complete("say something")

        assert str(raised.value)

    def test_an_empty_prompt_is_rejected_before_it_reaches_the_model(self, model):
        # Sending an empty prompt wastes a call and returns nothing useful.
        with pytest.raises(ModelFailed):
            model.complete("")
