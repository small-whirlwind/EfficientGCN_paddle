import paddle
import paddlenlp
import numpy as np
import paddle.nn as nn
import paddle.nn.functional as F


class EfficientGCN_Blocks(nn.Sequential):
    def __init__(self, init_channel, block_args, layer_type, kernel_size, input_channel=0, **kwargs):
        super(EfficientGCN_Blocks, self).__init__()

        temporal_window_size, max_graph_distance = kernel_size

        if input_channel > 0:  # if the blocks in the input branches

            self.add_sublayer('init_bn', nn.BatchNorm2D(input_channel, momentum=0.1))
            self.add_sublayer('stem_scn', Spatial_Graph_Layer(input_channel, init_channel, max_graph_distance, **kwargs))
            self.add_sublayer('stem_tcn', Temporal_Basic_Layer(init_channel, temporal_window_size, **kwargs))

        last_channel = init_channel
        # temporal_layer = U.import_class(f'src.model.layers.Temporal_{layer_type}_Layer')
        #temporal_layer = import_class('.layers.Temporal_'+layer_type+'_Layer')
        temporal_layer = import_class('models.backbones.efficientgcn.Temporal_'+layer_type+'_Layer')

        for i, [channel, stride, depth] in enumerate(block_args):
            # self.add_module(f'block-{i}_scn', Spatial_Graph_Layer(last_channel, channel, max_graph_distance, **kwargs))
            self.add_sublayer('block-'+str(i)+'_scn', Spatial_Graph_Layer(last_channel, channel, max_graph_distance, **kwargs))
            for j in range(depth):
                s = stride if j == 0 else 1
                # self.add_module(f'block-{i}_tcn-{j}', temporal_layer(channel, temporal_window_size, stride=s, **kwargs))
                self.add_sublayer('block-'+str(i)+'_tcn-'+str(j), temporal_layer(channel, temporal_window_size, stride=s, **kwargs))
            # self.add_module(f'block-{i}_att', Attention_Layer(channel, **kwargs))
            # self.add_module(f'block-{i}_att', Attention_Layer(channel, **kwargs))
            self.add_sublayer('block-'+str(i)+'_att', Attention_Layer(channel, **kwargs))
            last_channel = channel

def import_class(name):
    components = name.split('.')
    mod = __import__(components[0])
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod

# attentions.py
class Attention_Layer(nn.Layer):
    def __init__(self, out_channel, att_type, act, **kwargs):
        super(Attention_Layer, self).__init__()

        __attention = {
            'stja': ST_Joint_Att,
            'pa': Part_Att,
            'ca': Channel_Att,
            'fa': Frame_Att,
            'ja': Joint_Att,
        }

        self.att = __attention[att_type](channel=out_channel, **kwargs)
        self.bn = nn.BatchNorm2D(out_channel, momentum = 0.1)
        self.act = act

    def forward(self, x):
        res = x
        x = x * self.att(x)
        return self.act(self.bn(x) + res)


# class ST_Joint_Att(nn.Module):
class ST_Joint_Att(nn.Layer):
    def __init__(self, channel, reduct_ratio, bias, **kwargs):
        super(ST_Joint_Att, self).__init__()

        inner_channel = channel // reduct_ratio

        self.fcn = nn.Sequential(
            nn.Conv2D(channel, inner_channel, kernel_size=1, bias_attr = bias),
            nn.BatchNorm2D(inner_channel, momentum = 0.1),
            nn.Hardswish(),
        )
        self.conv_t = nn.Conv2D(inner_channel, channel, kernel_size=1, bias_attr=True)
        self.conv_v = nn.Conv2D(inner_channel, channel, kernel_size=1, bias_attr=True)

    def forward(self, x):
        N, C, T, V = x.shape
        # x_t = x.mean(3, keepdims=True)
        x_t = paddle.mean(x, 3, keepdim=True)
        # x_v = x.mean(2, keepdims=True).transpose(2, 3)
        x_v = paddle.mean(x, 2, keepdim=True)
        # print(x_v.shape)
        # x_v = x_v.transpose(2, 3)
        x_v = paddle.transpose(x_v, (0,1,3,2))
        # print(x_v.shape)
        # print(type(x_v.shape))
        # x_v[2] = 3
        # print(x_v.shape)
        # print(type(x_v.shape))
        # input('321')
        x_att = self.fcn(paddle.concat([x_t, x_v], axis=2))
        # x_t, x_v = torch.split(x_att, [T, V], dim=2)
        x_t, x_v = paddle.split(x_att, [T, V], axis=2)
        # x_t_att = self.conv_t(x_t).sigmoid()
        x_t_att = F.sigmoid(self.conv_t(x_t))
        # print(x_v.shape)
        x_v_att = F.sigmoid(self.conv_v(paddle.transpose(x_v,(0,1,3,2))))
        x_att = x_t_att * x_v_att
        return x_att


# class Part_Att(nn.Module):
class Part_Att(nn.Layer):
    def __init__(self, channel, parts, reduct_ratio, bias, **kwargs):
        super(Part_Att, self).__init__()

        self.parts = parts
        # self.joints = paddle.static.create_parameter(self.get_corr_joints(), requires_grad=False)
        # self.joints = paddle.static.create_parameter(self.get_corr_joints())
        self.joints = paddle.create_parameter(shape=self.get_corr_joints().shape,
                                    dtype='float32',
                            default_initializer=paddle.nn.initializer.Assign(self.get_corr_joints()))
        self.joints.stop_gradient = True
        inner_channel = channel // reduct_ratio

        # self.softmax = nn.Softmax(dim=3)
        self.softmax = nn.Softmax(axis=3)
        self.fcn = nn.Sequential(
            nn.AdaptiveAvgPool2D(1),
            nn.Conv2D(channel, inner_channel, kernel_size=1, bias_attr=bias),
            nn.BatchNorm2D(inner_channel, momentum=0.1),
            nn.ReLU(),
            nn.Conv2D(inner_channel, channel*len(self.parts), kernel_size=1, bias_attr=bias),
        )

    def forward(self, x):
        N, C, T, V = x.shape
        # x_att = self.softmax(self.fcn(x).view(N, C, 1, len(self.parts)))
        x_att = self.softmax(paddle.reshape(self.fcn(x), (N, C, 1, len(self.parts))))
        ###*******

        # x_att = x_att.index_select(3, self.joints).expand_as(x)
        x_att = paddle.index_select(x_att, axis=3, index = self.joints)
        x_att = paddle.expand_as(x_att, x)

        return x_att

    def get_corr_joints(self):
        num_joints = sum([len(part) for part in self.parts])
        joints = [j for i in range(num_joints) for j in range(len(self.parts)) if i in self.parts[j]]
        # return torch.LongTensor(joints)
        joints = paddle.to_tensor(joints)
        return paddle.cast(joints, 'int64')


# class Channel_Att(nn.Module):
class Channel_Att(nn.Layer):
    def __init__(self, channel, **kwargs):
        super(Channel_Att, self).__init__()

        self.fcn = nn.Sequential(
            nn.AdaptiveAvgPool2D(1),
            nn.Conv2D(channel, channel//4, kernel_size=1, bias_attr=True),
            nn.BatchNorm2D(channel//4, momentum=0.1),
            nn.ReLU(),
            nn.Conv2D(channel//4, channel, kernel_size=1, bias_attr=True),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.fcn(x)


# class Frame_Att(nn.Module):
class Frame_Att(nn.Layer):
    def __init__(self, **kwargs):
        super(Frame_Att, self).__init__()

        self.avg_pool = nn.AdaptiveAvgPool2D(1)
        self.max_pool = nn.AdaptiveMaxPool2D(1)
        self.conv = nn.Conv2D(2, 1, kernel_size=(9,1), padding=(4,0), bias_attr=True)

    def forward(self, x):
        # x = x.transpose(1, 2)
        xshape = x.shape
        tmp = xshape[1]
        xshape[1] = xshape[2]
        xshape[2] = tmp
        x = paddle.transpose(x, xshape)

        # x = paddle.concat([self.avg_pool(x), self.max_pool(x)], axis=2).transpose(1, 2)
        x = paddle.concat([self.avg_pool(x), self.max_pool(x)], axis=2)
        xshape2 = x.shape
        tmp = xshape2[1]
        xshape2[1] = xshape2[2]
        xshape2[2] = tmp
        x = paddle.transpose(x, xshape2)

        return self.conv(x)


# class Joint_Att(nn.Module):
class Joint_Att(nn.Layer):
    def __init__(self, parts, **kwargs):
        super(Joint_Att, self).__init__()

        num_joint = sum([len(part) for part in parts])

        self.fcn = nn.Sequential(
            nn.AdaptiveAvgPool2D(1),
            nn.Conv2D(num_joint, num_joint//2, kernel_size=1, bias_attr=True),
            nn.BatchNorm2D(num_joint//2, momentum=0.1),
            nn.ReLU(),
            nn.Conv2D(num_joint//2, num_joint, kernel_size=1, bias_attr=True),
            nn.Softmax(axis=1)
        )

    def forward(self, x):
        xshape = x.shape
        tmp = xshape[1]
        xshape[1] = xshape[3]
        xshape[3] = tmp
        x_trans = paddle.transpose(x, xshape)
        
        x_trans = self.fcn(x_trans)

        xshape2 = x.shape
        tmp = xshape2[1]
        xshape2[1] = xshape2[3]
        xshape2[3] = tmp
        x_trans = paddle.transpose(x_trans, xshape2)
        # return self.fcn(x.transpose(1, 3)).transpose(1, 3)

        return x_trans



# layers.py
class Basic_Layer(nn.Layer):
    def __init__(self, in_channel, out_channel, residual, bias, act, **kwargs):
        super(Basic_Layer, self).__init__()

        self.conv = nn.Conv2D(in_channel, out_channel, 1, bias_attr=bias)
        self.bn = nn.BatchNorm2D(out_channel, momentum=0.1)

        self.residual = nn.Identity() if residual else Zero_Layer()
        self.act = act


    def forward(self, x):
        res = self.residual(x)
        x = self.act(self.bn(self.conv(x)) + res)
        return x


class Spatial_Graph_Layer(Basic_Layer):
    def __init__(self, in_channel, out_channel, max_graph_distance, bias, residual=True, **kwargs):
        super(Spatial_Graph_Layer, self).__init__(in_channel, out_channel, residual, bias, **kwargs)

        self.conv = SpatialGraphConv(in_channel, out_channel, max_graph_distance, bias, **kwargs)
        if residual and in_channel != out_channel:
            self.residual = nn.Sequential(
                nn.Conv2D(in_channel, out_channel, 1, bias_attr=bias),
                nn.BatchNorm2D(out_channel, momentum=0.1),
            )


class Temporal_Basic_Layer(Basic_Layer):
    def __init__(self, channel, temporal_window_size, bias, stride=1, residual=True, **kwargs):
        super(Temporal_Basic_Layer, self).__init__(channel, channel, residual, bias, **kwargs)

        padding = (temporal_window_size - 1) // 2
        self.conv = nn.Conv2D(channel, channel, (temporal_window_size,1), (stride,1), (padding,0), bias_attr=bias)
        if residual and stride != 1:
            self.residual = nn.Sequential(
                nn.Conv2D(channel, channel, 1, (stride,1), bias_attr=bias),
                nn.BatchNorm2D(channel, momentum=0.1),
            )


class Temporal_Bottleneck_Layer(nn.Layer):
    def __init__(self, channel, temporal_window_size, bias, act, reduct_ratio, stride=1, residual=True, **kwargs):
        super(Temporal_Bottleneck_Layer, self).__init__()

        inner_channel = channel // reduct_ratio
        padding = (temporal_window_size - 1) // 2
        self.act = act

        self.reduct_conv = nn.Sequential(
            nn.Conv2D(channel, inner_channel, 1, bias_attr=bias),
            nn.BatchNorm2D(inner_channel, momentum=0.1),
        )
        self.conv = nn.Sequential(
            nn.Conv2D(inner_channel, inner_channel, (temporal_window_size,1), (stride,1), (padding,0), bias_attr=bias),
            nn.BatchNorm2D(inner_channel, momentum=0.1),
        )
        self.expand_conv = nn.Sequential(
            nn.Conv2D(inner_channel, channel, 1, bias_attr=bias),
            nn.BatchNorm2D(channel, momentum=0.1),
        )

        if not residual:
            self.residual = Zero_Layer()
        elif stride == 1:
            self.residual = nn.Identity()
        else:
            self.residual = nn.Sequential(
                nn.Conv2D(channel, channel, 1, (stride,1), bias_attr=bias),
                nn.BatchNorm2D(channel, momentum=0.1),
            )

    def forward(self, x):
        res = self.residual(x)
        x = self.act(self.reduct_conv(x))
        x = self.act(self.conv(x))
        x = self.act(self.expand_conv(x) + res)
        return x


# class Temporal_Sep_Layer(nn.Module):
class Temporal_Sep_Layer(nn.Layer):
    def __init__(self, channel, temporal_window_size, bias, act, expand_ratio, stride=1, residual=True, **kwargs):
        super(Temporal_Sep_Layer, self).__init__()

        padding = (temporal_window_size - 1) // 2
        self.act = act

        if expand_ratio > 0:
            inner_channel = channel * expand_ratio
            self.expand_conv = nn.Sequential(
                nn.Conv2D(channel, inner_channel, 1, bias_attr=bias),
                nn.BatchNorm2D(inner_channel, momentum=0.1),
            )
        else:
            inner_channel = channel
            self.expand_conv = None

        self.depth_conv = nn.Sequential(
            nn.Conv2D(inner_channel, inner_channel, (temporal_window_size,1), (stride,1), (padding,0), groups=inner_channel, bias_attr=bias),
            nn.BatchNorm2D(inner_channel, momentum=0.1),
        )
        self.point_conv = nn.Sequential(
            nn.Conv2D(inner_channel, channel, 1, bias_attr=bias),
            nn.BatchNorm2D(channel, momentum=0.1),
        )
        if not residual:
            self.residual = Zero_Layer()
        elif stride == 1:
            self.residual = nn.Identity()
        else:
            self.residual = nn.Sequential(
                nn.Conv2D(channel, channel, 1, (stride,1), bias_attr=bias),
                nn.BatchNorm2D(channel, momentum=0.1),
            )

    def forward(self, x):
        res = self.residual(x)
        if self.expand_conv is not None:
            x = self.act(self.expand_conv(x))
        x = self.act(self.depth_conv(x))
        x = self.point_conv(x)
        return x + res


# class Temporal_SG_Layer(nn.Module):
class Temporal_SG_Layer(nn.Layer):
    def __init__(self, channel, temporal_window_size, bias, act, reduct_ratio, stride=1, residual=True, **kwargs):
        super(Temporal_SG_Layer, self).__init__()

        padding = (temporal_window_size - 1) // 2
        inner_channel = channel // reduct_ratio
        self.act = act

        self.depth_conv1 = nn.Sequential(
            nn.Conv2D(channel, channel, (temporal_window_size,1), 1, (padding,0), groups=channel, bias_attr=bias),
            nn.BatchNorm2D(channel, momentum=0.1),
        )
        self.point_conv1 = nn.Sequential(
            nn.Conv2D(channel, inner_channel, 1, bias_attr=bias),
            nn.BatchNorm2D(inner_channel, momentum=0.1),
        )
        self.point_conv2 = nn.Sequential(
            nn.Conv2D(inner_channel, channel, 1, bias_attr=bias),
            nn.BatchNorm2D(channel, momentum=0.1),
        )
        self.depth_conv2 = nn.Sequential(
            nn.Conv2D(channel, channel, (temporal_window_size,1), (stride,1), (padding,0), groups=channel, bias_attr=bias),
            nn.BatchNorm2D(channel, momentum=0.1),
        )

        if not residual:
            self.residual = Zero_Layer()
        elif stride == 1:
            self.residual = nn.Identity()
        else:
            self.residual = nn.Sequential(
                nn.Conv2D(channel, channel, 1, (stride,1), bias_attr=bias),
                nn.BatchNorm2D(channel, momentum=0.1),
            )

    def forward(self, x):
        res = self.residual(x)
        x = self.act(self.depth_conv1(x))
        x = self.point_conv1(x)
        x = self.act(self.point_conv2(x))
        x = self.depth_conv2(x)
        return x + res


# class Zero_Layer(nn.Module):
class Zero_Layer(nn.Layer):
    def __init__(self):
        super(Zero_Layer, self).__init__()

    def forward(self, x):
        return 0


# Thanks to YAN Sijie for the released code on Github (https://github.com/yysijie/st-gcn)
# class SpatialGraphConv(nn.Module):
class SpatialGraphConv(nn.Layer):
    def __init__(self, in_channel, out_channel, max_graph_distance, bias, edge, A, **kwargs):
        super(SpatialGraphConv, self).__init__()

        self.s_kernel_size = max_graph_distance + 1
        self.gcn = nn.Conv2D(in_channel, out_channel*self.s_kernel_size, 1, bias_attr=bias)
        # self.A = nn.Parameter(A[:self.s_kernel_size], requires_grad=False)
        # self.A = paddle.static.create_parameter(A[:self.s_kernel_size], dtype="float32")
        self.A = paddle.create_parameter(shape=A[:self.s_kernel_size].shape, 
                                        dtype='float32', 
                    default_initializer=paddle.nn.initializer.Assign(A[:self.s_kernel_size]))
        self.A.stop_gradient = True

        if edge:
            # self.edge = paddle.static.create_parameter(paddle.ones_like(self.A),dtype="float32")
            self.edge = paddle.create_parameter(shape=paddle.ones_like(self.A).shape,
                                        dtype='float32',
                    default_initializer=paddle.nn.initializer.Assign(paddle.ones_like(self.A)))
            self.edge.stop_gradient = False
        else:
            self.edge = 1

    def forward(self, x):
        x = self.gcn(x)
        n, kc, t, v = x.shape
        # x = x.view(n, self.s_kernel_size, kc//self.s_kernel_size, t, v)
        x = paddle.reshape(x, (n, self.s_kernel_size, kc//self.s_kernel_size, t, v))
        # print(n, kc, t, v, self.s_kernel_size, kc//self.s_kernel_size, self.edge)
        
        # x = torch.einsum('nkctv,kvw->nctw', (x, self.A * self.edge)).contiguous()

        ###
        ## 
        # ---------为对齐，暂时消掉该操作，待正式训练前恢复-----------
        # x = paddle.reshape(x[:,0,:,:,:], [n, kc//self.s_kernel_size, t, v])
        x = paddlenlp.ops.einsum('nkctv,kvw->nctw', x, self.A * self.edge)
        return x    






# activations.py
class Swish(nn.Layer):
    def __init__(self, inplace=False):
        super(Swish, self).__init__()
        self.inplace = inplace
        

    def forward(self, x):
        # return x.mul_(F.sigmoid(x)) if self.inplace else x.mul(F.sigmoid(x))
        return paddle.multiply(x,F.sigmoid(x)) if self.inplace else paddle.multiply(x,F.sigmoid(x))
        
# class HardSwish(nn.Module):
class HardSwish(nn.Layer):
    def __init__(self, inplace=False):
        super(HardSwish, self).__init__()
        self.inplace = inplace

    def forward(self, x):
        inner = nn.functional.relu6(x + 3.).div_(6.)
        tmp_div = paddle.full(shape=inner.shape, fill_value=6. , dtype='float64')
        inner = paddle.divide(inner, tmp_div)
        # return x.mul_(inner) if self.inplace else x.mul(inner)
        return paddle.multiply(x,inner) if self.inplace else paddle.multiply(x, inner)

# class AconC(nn.Module):
class AconC(nn.Layer):
    r""" ACON activation (activate or not).
    # AconC: (p1*x-p2*x) * sigmoid(beta*(p1*x-p2*x)) + p2*x, beta is a learnable parameter
    # according to "Activate or Not: Learning Customized Activation" <https://arxiv.org/pdf/2009.04759.pdf>.
    """
    def __init__(self, channel):
        super(AconC).__init__()
        # self.p1 = nn.Parameter(torch.randn(1, channel, 1, 1))       
        # self.p1 = paddle.static.create_parameter(paddle.randn([1, channel, 1, 1]))
        self.p1 = paddle.create_parameter(shape=[1, channel, 1, 1], 
                                        dtype='float32', 
                            default_initializer=paddle.nn.initializer.Assign(paddle.randn([1, channel, 1, 1])))
        self.p1.stop_gradient = False
        # self.p2 = nn.Parameter(torch.randn(1, channel, 1, 1))
        # self.p2 = paddle.static.create_parameter(paddle.randn([1, channel, 1, 1]))
        self.p2 = paddle.create_parameter(shape=[1,channel,1,1],
                                    dtype='float32',
                            default_initializer=paddle.nn.initializer.Assign(paddle.randn([1, channel, 1, 1])))
        self.p2.stop_gradient = False
        # self.beta = nn.Parameter(torch.ones(1, channel, 1, 1))
        # self.beta = paddle.static.create_parameter(paddle.ones([1, channel, 1, 1]))
        self.beta = paddle.create_parameter(shape=[1,channel,1,1],
                                    dtype='float32',
                            default_initializer=paddle.nn.initializer.Assign(paddle.ones([1, channel, 1, 1])))
        self.beta.stop_gradient = False

    def forward(self, x):
        return F.sigmoid((self.p1 * x - self.p2 * x) * (self.beta * (self.p1 * x - self.p2 * x))) + self.p2 * x

# class MetaAconC(nn.Module):
class MetaAconC(nn.Layer):
    r""" ACON activation (activate or not).
    # MetaAconC: (p1*x-p2*x) * sigmoid(beta*(p1*x-p2*x)) + p2*x, beta is generated by a small network
    # according to "Activate or Not: Learning Customized Activation" <https://arxiv.org/pdf/2009.04759.pdf>.
    """
    def __init__(self, channel, r=4):
        super().__init__()
        inner_channel = max(r, channel // r)
        # self.fcn = nn.Sequential(
        #     nn.AdaptiveAvgPool2d(1),
        #     nn.Conv2d(channel, inner_channel, 1),
        #     nn.BatchNorm2d(inner_channel),
        #     nn.Conv2d(inner_channel, channel, 1),
        #     nn.BatchNorm2d(channel),
        #     nn.Sigmoid(),
        # )

        self.fcn = nn.Sequential(
            nn.AdaptiveAvgPool2D(1),
            nn.Conv2D(channel, inner_channel, 1, bias_attr = True),
            nn.BatchNorm2D(inner_channel, momentum=0.1),
            nn.Conv2D(inner_channel, channel, 1, bias_attr = True),
            nn.BatchNorm2D(channel, momentum= 0.1),
            nn.Sigmoid(),
        )

        # self.p1 = nn.Parameter(paddle.randn([1, channel, 1, 1]))
        # self.p2 = nn.Parameter(paddle.randn([1, channel, 1, 1]))
        self.p1 = paddle.create_parameter(shape=[1, channel, 1, 1], 
                                        dtype='float32', 
                            default_initializer=paddle.nn.initializer.Assign(paddle.randn([1, channel, 1, 1])))
        self.p1.stop_gradient = False
        
        self.p2 = paddle.create_parameter(shape=[1,channel,1,1],
                                    dtype='float32',
                            default_initializer=paddle.nn.initializer.Assign(paddle.randn([1, channel, 1, 1])))
        self.p2.stop_gradient = False

    def forward(self, x, **kwargs):
        return F.sigmoid((self.p1 * x - self.p2 * x) * (self.fcn(x) * (self.p1 * x - self.p2 * x))) + self.p2 * x