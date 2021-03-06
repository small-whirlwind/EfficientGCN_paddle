import paddle
import paddle.nn as nn
import paddle.nn.initializer as init
from scipy import special
import numpy as np
import math
from ..heads import EfficientGCN_Classifier
from ..backbones import EfficientGCN_Blocks
class EfficientGCN(nn.Layer):
    def __init__(self, data_shape, block_args, fusion_stage, stem_channel, **kwargs):
        super(EfficientGCN, self).__init__()

        num_input, num_channel, _, _, _ = data_shape

        self.input_branches = nn.LayerList([EfficientGCN_Blocks(
            init_channel = stem_channel,
            block_args = block_args[:fusion_stage],
            input_channel = num_channel,
            **kwargs
        ) for _ in range(num_input)])

        # main stream
        last_channel = stem_channel if fusion_stage == 0 else block_args[fusion_stage-1][0]
        self.main_stream = EfficientGCN_Blocks(
            init_channel = num_input * last_channel,
            block_args = block_args[fusion_stage:],
            **kwargs
        )

        # output
        last_channel = num_input * block_args[-1][0] if fusion_stage == len(block_args) else block_args[-1][0]
        self.classifier = EfficientGCN_Classifier(last_channel, **kwargs)

        # init parameters
        init_param(self.sublayers())

    def forward(self, x):

        N, I, C, T, V, M = x.shape
        x = paddle.transpose(x, [1, 0, 5, 2, 3, 4])
        x = paddle.reshape(x, [I, N*M, C, T, V])
    

        x = paddle.concat([branch(x[i]) for i, branch in enumerate(self.input_branches)], axis=1)
        # main stream
        x = self.main_stream(x)
        # output
        _, C, T, V = x.shape

        # feature = x.view(N, M, C, T, V).permute(0, 2, 3, 4, 1)
        feature = paddle.reshape(x, [N, M, C, T, V])
        feature = paddle.transpose(feature, [0, 2, 3, 4, 1])

        out = paddle.reshape(self.classifier(feature), [N, -1])

        return out, feature 

def init_param(layers):
    # === 不太一样      换成他的跑一跑
    for m in layers:
        if isinstance(m, nn.Conv1D) or isinstance(m, nn.Conv2D):
            m.weight = kaiming_normal_(m.weight, mode='fan_out', nonlinearity='leaky_relu')
            if m.bias is not None:
                nn.initializer.Constant(0)(m.bias)
        elif isinstance(m, nn.BatchNorm1D) or isinstance(m, nn.BatchNorm2D) or isinstance(m, nn.BatchNorm3D):
            nn.initializer.Constant(1)(m.weight)
            nn.initializer.Constant(0)(m.bias)
        elif isinstance(m, nn.Conv3D) or isinstance(m, nn.Linear):
            nn.initializer.Normal(std=0.001)(m.weight)
            if m.bias is not None:
                nn.initializer.Constant(0)(m.bias)
    # for l in layers:
    #     if isinstance(l, nn.Conv1D) or isinstance(l, nn.Conv2D):
            
    #         # v = np.random.normal(loc=0.,scale=np.sqrt(2./n),size=l.weight.shape).astype('float32')
    #         print('it\'s ok for initial')
    #         l.weight.set_value(kaiming_normal_1(l.weight, mode='fan_out'))
    #         # nn.init.kaiming_normal_(l.weight, mode='fan_out', nonlinearity='leaky_relu')
    #         if l.bias is not None:
    #             # l.bias.set_value(0)
    #             l.bias.set_value(zeros_1(l.bias))
                
    #     elif isinstance(l, nn.BatchNorm1D) or isinstance(l, nn.BatchNorm2D) or isinstance(l, nn.BatchNorm3D):
    #         l.weight.set_value(ones_1(l.weight))
    #         l.bias.set_value(zeros_1(l.bias))
    #     elif isinstance(l, nn.Conv3D) or isinstance(l, nn.Linear):
    #         l.weight.set_value(normal_1(l.weight))
    #         l.bias.set_value(zeros_1(l.bias))




            
def weight_init_(layer,
                 func,
                 weight_name=None,
                 bias_name=None,
                 bias_value=0.0,
                 **kwargs):
    """
    In-place params init function.
    Usage:
    .. code-block:: python

        import paddle
        import numpy as np

        data = np.ones([3, 4], dtype='float32')
        linear = paddle.nn.Linear(4, 4)
        input = paddle.to_tensor(data)
        print(linear.weight)
        linear(input)

        weight_init_(linear, 'Normal', 'fc_w0', 'fc_b0', std=0.01, mean=0.1)
        print(linear.weight)
    """

    if hasattr(layer, 'weight') and layer.weight is not None:
        getattr(init, func)(**kwargs)(layer.weight)
        if weight_name is not None:
            # override weight name
            layer.weight.name = weight_name

    if hasattr(layer, 'bias') and layer.bias is not None:
        init.Constant(bias_value)(layer.bias)
        if bias_name is not None:
            # override bias name
            layer.bias.name = bias_name


def _no_grad_trunc_normal_(tensor, mean, std, a, b):
    def norm_cdf(x):
        # Computes standard normal cumulative distribution function
        return (1. + math.erf(x / math.sqrt(2.))) / 2.

    if (mean < a - 2 * std) or (mean > b + 2 * std):
        print("mean is more than 2 std from [a, b] in nn.init.trunc_normal_. "
              "The distribution of values may be incorrect.")

    with paddle.no_grad():
        # Values are generated by using a truncated uniform distribution and
        # then using the inverse CDF for the normal distribution.
        # Get upper and lower cdf values
        l = norm_cdf((a - mean) / std)
        u = norm_cdf((b - mean) / std)

        # Uniformly fill tensor with values from [l, u], then translate to [2l-1, 2u-1].
        tmp = np.random.uniform(2 * l - 1, 2 * u - 1,
                                size=list(tensor.shape)).astype(np.float32)

        # Use inverse cdf transform for normal distribution to get truncated
        # standard normal
        tmp = special.erfinv(tmp)

        # Transform to proper mean, std
        tmp *= (std * math.sqrt(2.0))
        tmp += mean

        # Clamp to ensure it's in the proper range
        tmp = np.clip(tmp, a, b)
        tensor.set_value(paddle.to_tensor(tmp))

        return tensor


def _calculate_fan_in_and_fan_out(tensor):
    dimensions = tensor.dim()
    if dimensions < 2:
        raise ValueError(
            "Fan in and fan out can not be computed for tensor with fewer than 2 dimensions"
        )

    num_input_fmaps = tensor.shape[1]
    num_output_fmaps = tensor.shape[0]
    receptive_field_size = 1
    if tensor.dim() > 2:
        receptive_field_size = tensor[0][0].numel()
    fan_in = num_input_fmaps * receptive_field_size
    fan_out = num_output_fmaps * receptive_field_size

    return fan_in, fan_out


def trunc_normal_(tensor, mean=0., std=1., a=-2., b=2.):
    return _no_grad_trunc_normal_(tensor, mean, std, a, b)


def kaiming_normal_(tensor, a=0., mode='fan_in', nonlinearity='leaky_relu'):
    def _calculate_correct_fan(tensor, mode):
        mode = mode.lower()
        valid_modes = ['fan_in', 'fan_out']
        if mode not in valid_modes:
            raise ValueError(
                "Mode {} not supported, please use one of {}".format(
                    mode, valid_modes))

        fan_in, fan_out = _calculate_fan_in_and_fan_out(tensor)
        return fan_in if mode == 'fan_in' else fan_out

    def calculate_gain(nonlinearity, param=None):
        linear_fns = [
            'linear', 'conv1d', 'conv2d', 'conv3d', 'conv_transpose1d',
            'conv_transpose2d', 'conv_transpose3d'
        ]
        if nonlinearity in linear_fns or nonlinearity == 'sigmoid':
            return 1
        elif nonlinearity == 'tanh':
            return 5.0 / 3
        elif nonlinearity == 'relu':
            return math.sqrt(2.0)
        elif nonlinearity == 'leaky_relu':
            if param is None:
                negative_slope = 0.01
            elif not isinstance(param, bool) and isinstance(
                    param, int) or isinstance(param, float):
                negative_slope = param
            else:
                raise ValueError(
                    "negative_slope {} not a valid number".format(param))
            return math.sqrt(2.0 / (1 + negative_slope**2))
        else:
            raise ValueError("Unsupported nonlinearity {}".format(nonlinearity))

    fan = _calculate_correct_fan(tensor, mode)
    gain = calculate_gain(nonlinearity, a)
    std = gain / math.sqrt(fan)
    with paddle.no_grad():
        paddle.nn.initializer.Normal(0, std)(tensor)
        return tensor