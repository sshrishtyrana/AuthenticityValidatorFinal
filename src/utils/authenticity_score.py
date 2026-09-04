def calculate_authenticity_score(ai_score, similarity_score):
    """
    Combine AI-pattern and similarity results into
    an overall authenticity score.

    ai_score:
        Rule-based AI pattern score.

    similarity_score:
        Similarity score between 0 and 1.
    """

    # AI score is currently based on 0-3 indicators.
    ai_normalized = min(ai_score / 3, 1)

    # Higher similarity means lower originality.
    similarity_risk = similarity_score

    # Weighted risk calculation.
    risk_score = (
        0.40 * ai_normalized +
        0.60 * similarity_risk
    )

    authenticity_score = (1 - risk_score) * 100

    return round(authenticity_score, 2)


def classify_authenticity(score):
    """
    Convert the numerical score into an easy-to-understand category.
    """

    if score >= 80:
        return "High Authenticity"
    elif score >= 60:
        return "Moderate Authenticity"
    elif score >= 40:
        return "Low Authenticity"
    else:
        return "Very Low Authenticity"


def generate_result(ai_score, similarity_score):
    """
    Generate the final authenticity assessment.
    """

    score = calculate_authenticity_score(
        ai_score,
        similarity_score
    )

    classification = classify_authenticity(score)

    return {
        "authenticity_score": score,
        "classification": classification,
        "ai_risk_score": ai_score,
        "similarity_score": similarity_score
    }


if __name__ == "__main__":

    # Example test values
    ai_score = 1
    similarity_score = 0.25

    result = generate_result(
        ai_score,
        similarity_score
    )

    print("Authenticity Assessment")
    print("-----------------------")
    print("Authenticity Score:", result["authenticity_score"])
    print("Classification:", result["classification"])
    print("AI Risk Score:", result["ai_risk_score"])
    print("Similarity Score:", result["similarity_score"])