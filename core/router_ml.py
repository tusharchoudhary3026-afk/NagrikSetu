# """Engine 3: TF-IDF + Logistic Regression. TODO after the baseline is evaluated."""
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.linear_model import LogisticRegression
# from .config import CONFIDENCE_THRESHOLD


# class TfidfRouter:
#     def __init__(self):
#         self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
#         self.clf = LogisticRegression(max_iter=1000)

#     def fit(self, texts, labels):
#         self.clf.fit(self.vec.fit_transform(texts), labels)
#         return self

#     def route(self, text, threshold=CONFIDENCE_THRESHOLD):
#         X = self.vec.transform([text])
#         probs = self.clf.predict_proba(X)[0]
#         order = probs.argsort()[::-1][:3]
#         top3 = [{"dept": self.clf.classes_[i], "score": round(float(probs[i]), 2)} for i in order]
#         names = self.vec.get_feature_names_out()
#         nz = X.nonzero()[1]
#         evidence = {"matched_terms": [names[i] for i in nz][:8]}   # grounded in the input text
#         conf = top3[0]["score"]          # NOT assumed calibrated
#         return {"top3": top3, "evidence": evidence, "confidence": conf, "abstained": conf < threshold}


"""Engine 3: TF-IDF + Logistic Regression with Evaluation & Threshold Tuning."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from .config import CONFIDENCE_THRESHOLD


class TfidfRouter:
    def __init__(self):
        self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self.clf = LogisticRegression(max_iter=1000)

    def fit(self, texts, labels):
        self.clf.fit(self.vec.fit_transform(texts), labels)
        return self

    def route(self, text, threshold=CONFIDENCE_THRESHOLD):
        X = self.vec.transform([text])
        probs = self.clf.predict_proba(X)[0]
        order = probs.argsort()[::-1][:3]
        top3 = [{"dept": self.clf.classes_[i], "score": round(float(probs[i]), 2)} for i in order]
        
        # Keep only tokens present in both the complaint and fitted vocabulary.
        names = self.vec.get_feature_names_out()
        tokens = text.lower().split()
        matched = [w for w in tokens if w in names][:8]
        evidence = {"matched_terms": matched}
        
        conf = top3[0]["score"]
        # No threshold selected on validation means the model is not cleared to
        # answer; keep evidence visible but send every case to human review.
        return {"top3": top3, "evidence": evidence, "confidence": conf,
                "abstained": threshold is None or conf < threshold}


def single_owner_rows(df):
    """Filters dataset for single-owner rows (excluding MULTI and UNCLEAR)."""
    if "owner_label" in df.columns:
        return df[~df["owner_label"].isin(["MULTI", "UNCLEAR"])]
    return df


def fit_default(df):
    """Fit only on rows explicitly marked train when a grouped split is present."""
    if "split" in df.columns:
        df = df[df["split"] == "train"]
        if df.empty:
            raise ValueError("No training rows are available; validation/test data cannot fit the router.")
    train_df = single_owner_rows(df)
    if train_df.empty:
        raise ValueError("No single-owner training rows are available.")
    router = TfidfRouter()
    router.fit(train_df["text"], train_df["owner_label"])
    return router


def choose_threshold(router, val_df, min_coverage=0.25):
    """Choose a threshold from validation data only; prefer accuracy, then coverage."""
    if "split" in val_df.columns:
        val_df = val_df[val_df["split"] == "val"]
    val_df = single_owner_rows(val_df)
    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    curve = []
    
    for th in thresholds:
        correct, total = 0, 0
        for _, r in val_df.iterrows():
            text = r.get("text", r.get("original_text", ""))
            label = r.get("owner_label")
            res = router.route(text, threshold=th)
            if not res["abstained"]:
                total += 1
                if label and res["top3"] and res["top3"][0]["dept"] == label:
                    correct += 1
        acc = correct / total if total > 0 else 0.0
        coverage = total / len(val_df) if len(val_df) > 0 else 0.0
        curve.append({"threshold": th, "accuracy": acc, "coverage": coverage, "answered": total})

    eligible = [row for row in curve if row["coverage"] >= min_coverage and row["answered"]]
    if not eligible:
        # Do not silently install a default threshold when validation cannot
        # meet its stated coverage target. `None` means abstain on every result.
        return None, curve
    best = max(eligible, key=lambda row: (row["accuracy"], row["coverage"], row["threshold"]))
    return best["threshold"], curve
