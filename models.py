from xgboost import XGBRegressor, XGBClassifier


def train_models(X_train, y_cls_train, y_reg_train):

    models = {}

    # classification model (trade filter)
    models["xgb_cls"] = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8
    )

    # Binary labels from features: 0 = down, 1 = up
    y_cls_encoded = y_cls_train.astype(int)
    models["xgb_cls"].fit(X_train, y_cls_encoded)

    # regression model (return magnitude)
    models["xgb_reg"] = XGBRegressor(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8
    )

    models["xgb_reg"].fit(X_train, y_reg_train)

    return models


def predict(models, X):

    # Binary classifier: column 1 is P(up)
    proba_up = models["xgb_cls"].predict_proba(X)[:, 1]
    pred_ret = models["xgb_reg"].predict(X)

    
    return {
        "proba": proba_up,
        "ret": pred_ret
    }