from src.custom.google_gemini_2_0_flash.models.google_gemini_2_0_flash import model

def test_gemini_model():
    response = model.model.invoke("Hello, who are you?")
    assert response.content is not None