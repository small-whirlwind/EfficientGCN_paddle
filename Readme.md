# EfficientGCN_paddle
This is an unofficial code based on PaddlePaddle of IEEE 2022 paper:

EfficientGCN: Constructing Stronger and Faster Baselines for Skeleton-based Action Recognition

https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=9729609

该模型在MIB网络中结合可分离的卷积层，利用图卷积网络对视频动作进行识别，骨骼点数据相对于传统RGB数据更具解释性与鲁棒性。该方法相较于传统中参数量较大的双流特征提取方式，在模型的前端选择融合三个输入分支并输入主流模型提取特征，通过这种方式减小了模型的复杂度。
