import paddle.nn as nn

class EfficientGCN_Classifier(nn.Sequential):
    def __init__(self, curr_channel, num_class, drop_prob, **kwargs):
        super(EfficientGCN_Classifier, self).__init__()

        # self.add_module('gap', nn.AdaptiveAvgPool3d(1))
        # self.add_module('dropout', nn.Dropout(drop_prob, inplace=True))
        # self.add_module('fc', nn.Conv3d(curr_channel, num_class, kernel_size=1))
        self.add_sublayer('gap', nn.AdaptiveAvgPool3D(1))
        self.add_sublayer('dropout', nn.Dropout(drop_prob))
        self.add_sublayer('fc', nn.Conv3D(curr_channel, num_class, kernel_size=1, bias_attr=True))