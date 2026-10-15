"""Safe user-facing errors; never include credentials or raw upstream responses."""
class ShopCheckError(RuntimeError):
    pass

class AuthExpiredError(ShopCheckError):
    pass

class RenewalError(ShopCheckError):
    """Only endpoint name, numeric code and fixed reason labels are retained."""
    def __init__(self, stage, code, *, reason='upstream', rejected=False):
        self.stage, self.code, self.reason, self.rejected = stage, code, reason, rejected
        super().__init__('掌瓦登录续期未完成，请稍后重试。')

class BindingError(ShopCheckError):
    pass

class DeliveryRejected(ShopCheckError):
    """Sender has definite evidence that no message was accepted."""
    pass
