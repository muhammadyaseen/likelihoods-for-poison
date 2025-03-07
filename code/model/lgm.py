import torch
import torch.nn as nn
from torch.autograd import Variable


class LGMLoss(nn.Module):
    """
    Refer to paper:
    Weitao Wan, Yuanyi Zhong,Tianpeng Li, Jiansheng Chen
    Rethinking Feature Distribution for Loss Functions in Image Classification. CVPR 2018
    re-implement by yirong mao
    2018 07/02
    """

    def __init__(self, num_classes, feat_dim, alpha):
        super(LGMLoss, self).__init__()
        self.feat_dim = feat_dim
        self.num_classes = num_classes
        self.alpha = alpha

        self.centers = nn.Parameter(torch.randn(num_classes, feat_dim))
        self.log_covs = nn.Parameter(torch.zeros(num_classes, feat_dim))

    def forward(self, feat, label):
        batch_size = feat.shape[0]
        log_covs = torch.unsqueeze(self.log_covs, dim=0)

        covs = torch.exp(log_covs)  # 1*c*d
        tcovs = covs.repeat(batch_size, 1, 1)  # n*c*d
        diff = torch.unsqueeze(feat, dim=1) - torch.unsqueeze(self.centers, dim=0)
        wdiff = torch.div(diff, tcovs)
        diff = torch.mul(diff, wdiff)
        dist = torch.sum(diff, dim=-1)  # eq.(18)

        y_onehot = torch.FloatTensor(batch_size, self.num_classes)
        y_onehot.zero_()
        y_onehot = Variable(y_onehot).cuda()
        y_onehot.scatter_(1, torch.unsqueeze(label, dim=-1), self.alpha)
        y_onehot = y_onehot + 1.0
        margin_dist = torch.mul(dist, y_onehot)

        slog_covs = torch.sum(log_covs, dim=-1)  # 1*c
        tslog_covs = slog_covs.repeat(batch_size, 1)
        margin_logits = -0.5 * (tslog_covs + margin_dist)  # eq.(17)
        logits = -0.5 * (tslog_covs + dist)

        # calc of L_lkd
        cdiff = feat - torch.index_select(self.centers, dim=0, index=label.long())
        cdist = cdiff.pow(2).sum(1).sum(0) / 2.0

        slog_covs = torch.squeeze(slog_covs)
        reg = 0.5 * torch.sum(torch.index_select(slog_covs, dim=0, index=label.long()))
        likelihood = (1.0 / batch_size) * (cdist + reg)

        return logits, margin_logits, likelihood


class LGMLoss_v0(nn.Module):
    """
    LGMLoss whose covariance is fixed as Identity matrix
    """

    def __init__(self, num_classes, feat_dim, alpha):
        super(LGMLoss_v0, self).__init__()
        self.feat_dim = feat_dim
        self.num_classes = num_classes
        self.alpha = alpha

        self.centers = nn.Parameter(torch.randn(num_classes, feat_dim))

    def forward(self, feat, label):
        batch_size = feat.shape[0]

        # calc of d_k
        diff = torch.unsqueeze(feat, dim=1) - torch.unsqueeze(self.centers, dim=0)
        diff = torch.mul(diff, diff)
        dist = torch.sum(diff, dim=-1)              # eq.(18)

        # calc of 1 + I(k = z_i)*alpha
        y_onehot = torch.FloatTensor(batch_size, self.num_classes)
        y_onehot.zero_()
        y_onehot = Variable(y_onehot).cuda()
        #y_onehot = Variable(y_onehot)
        y_onehot.scatter_(1, torch.unsqueeze(label, dim=-1), self.alpha)
        y_onehot = y_onehot + 1.0

        margin_dist = torch.mul(dist, y_onehot)
        margin_logits = -0.5 * margin_dist          # eq.(17)
        logits = -0.5 * dist

        # calc of L_lkd
        cdiff = feat - torch.index_select(self.centers, dim=0, index=label.long())
        likelihood = (1.0 / batch_size) * cdiff.pow(2).sum(1).sum(0) / 2.0
        return logits, margin_logits, likelihood

class LGMUtils:

    @staticmethod
    def is_anomalous(model, claimed_class, X):
        # we check if the input X which is claiming to be in `claimed_class` is an anomaly
        # in the feature space or not (under Gaussian feature distribution)
        # The assumption is that LGM should return lower likelihood of X  belonging to `claimed_class`
        # if X is poisoned.

        _, feats = model(X)
        logits, _, _ = model.lgm(feat=feats, label=claimed_class)
        _, predicted = torch.max(logits.data, 1)
        return predicted != claimed_class

    @staticmethod
    def get_likelihood(model, claimed_class, X):

        # we check if the input X which is claiming to be in `claimed_class` is an anomaly
        # in the feature space or not (under Gaussian feature distribution)
        # The assumption is that LGM should return lower likelihood of X  belonging to `claimed_class`
        # if X is poisoned.

        with torch.no_grad():

            # computer 2D features under learned likelihood
            _, feats = model(X)
            # feature mean of class X is claiming to belong to
            fmean = model.lgm.centers[claimed_class]
            # likelihood (as explained in 1st para of Adversarial Verification section in 4.3)
            # feat and fmean should be size [1,2] tensors
            lkd = torch.exp(-0.5*(feats - fmean).norm(p=2, dim=1)**2)

            return lkd


if __name__ == "__main__":
    # load model and test
    from torch.utils.data import DataLoader
    from torchvision import datasets, transforms
    import torch
    from data.poisons import Poison

    bsize = 4
    tfsm = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,))
    ])

    trainset = datasets.MNIST('../datasets/', download=True, train=True, transform=tfsm)
    train_loader = DataLoader(trainset, batch_size=bsize, shuffle=False, num_workers=4)
    poisoned_dataset = Poison('../experiments/mnist_lgm_poisons/lgm-model', tfsm)
    poisoned_loader = DataLoader(poisoned_dataset, batch_size=bsize, shuffle=False, num_workers=4)

    # for cifar
    trainset_cifar = datasets.CIFAR('../datasets/', download=True, train=False, transform=tfsm)
    train_loader_cifar = DataLoader(trainset_cifar, batch_size=bsize, shuffle=False, num_workers=4)
    poisoned_dataset_cifar = Poison('../checkpoints/LGM-cifar-vgg/LGM-vgg-cifar.epoch-10-.model', tfsm)
    poisoned_loader_cifar = DataLoader(poisoned_dataset, batch_size=bsize, shuffle=False, num_workers=4)

    # load a model
    from .net import MNISTNet
    from .net import VGG
    import pdb
    import matplotlib.pyplot as plt
    import numpy as np
    import scikitplot as skplt

    model = MNISTNet(use_lgm=True).cuda()
    model.load_state_dict(torch.load('../experiments/lgm_mnist/lgm-model'), strict=False)

    lkd_hist = []
    for i, (X, Y) in enumerate(train_loader):
        X = X.cuda()
        Y = Y.cuda()
        lkd = LGMUtils.get_likelihood(model, Y, X)
        lkd_hist.extend(lkd.cpu().numpy())
        #if i*bsize >= 100: break

    plkd_hist = []
    for X, Y, _ in poisoned_loader:
        X = X.cuda()
        Y = Y.cuda()
        lkd = LGMUtils.get_likelihood(model, Y, X)
        plkd_hist.extend(lkd.cpu().numpy())

    fig, ax1 = plt.subplots()
    color = 'tab:green'
    ax1.set_xlabel('Likelihood Histogram')
    ax1.set_ylabel('Clean Data')
    ax1.hist(lkd_hist, bins=np.arange(0, 1.05, 0.05), align='mid', histtype='bar', color=color, alpha=0.7,
             label='Clean Data')
    ax1.tick_params(axis='y', labelcolor=color)

    color = 'tab:red'
    ax2 = ax1.twinx()
    ax2.set_ylabel('Poisoned Data')
    ax2.hist(plkd_hist, bins=np.arange(0, 1.05, 0.05), align='mid', histtype='bar', color=color, alpha=0.7,
             label='Poisoned Data')
    ax2.tick_params(axis='y', labelcolor=color)

    # fig.tight_layout()
    plt.gca().set_title('Likelihood histogram on normal and poisoned data')
    ax1.legend(loc=1)
    ax2.legend(loc=2)
    plt.savefig('./histall.jpg')

    # plot ROC

    Y = np.concatenate((np.zeros(len(lkd_hist)), np.ones(len(plkd_hist))))
    Y = Y.reshape(len(Y), 1)
    print(Y.shape)

    lkd_hist = np.array(lkd_hist).reshape(len(lkd_hist), 1)
    lkd_hist = np.concatenate((lkd_hist, 1 - lkd_hist), axis=1)

    plkd_hist = np.array(plkd_hist).reshape(len(plkd_hist), 1)
    plkd_hist = np.concatenate((plkd_hist, 1 - plkd_hist), axis=1)
    Yp = np.concatenate((lkd_hist, plkd_hist))

    ###
    # For CIFAR
    ###

    model = VGG(vgg_name='VGG19', use_lgm=True).cuda()
    model.load_state_dict(torch.load('../checkpoints/LGM-cifar-vgg/LGM-vgg-cifar.epoch-10-.model'), strict=False)

    lkd_hist = []
    for i, (X, Y) in enumerate(train_loader_cifar):
        X = X.cuda()
        Y = Y.cuda()
        lkd = LGMUtils.get_likelihood(model, Y, X)
        lkd_hist.extend(lkd.cpu().numpy())

    plkd_hist = []
    for X, Y, _ in poisoned_loader_cifar:
        X = X.cuda()
        Y = Y.cuda()
        lkd = LGMUtils.get_likelihood(model, Y, X)
        plkd_hist.extend(lkd.cpu().numpy())

    fig, ax1 = plt.subplots()
    color = 'tab:green'
    ax1.set_xlabel('Likelihood Histogram')
    ax1.set_ylabel('Clean Data')
    ax1.hist(lkd_hist, bins=np.arange(0, 1.05, 0.05), align='mid', histtype='bar', color=color, alpha=0.7,
             label='Clean Data')
    ax1.tick_params(axis='y', labelcolor=color)

    color = 'tab:red'
    ax2 = ax1.twinx()
    ax2.set_ylabel('Poisoned Data')
    ax2.hist(plkd_hist, bins=np.arange(0, 1.05, 0.05), align='mid', histtype='bar', color=color, alpha=0.7,
             label='Poisoned Data')
    ax2.tick_params(axis='y', labelcolor=color)

    # fig.tight_layout()
    plt.gca().set_title('Likelihood histogram on normal and poisoned data')
    ax1.legend(loc=1)
    ax2.legend(loc=2)
    plt.savefig('./histall_cifar.jpg')

    # plot ROC

    Yc = np.concatenate((np.zeros(len(lkd_hist)), np.ones(len(plkd_hist))))
    Yc = Y.reshape(len(Y), 1)
    print(Yc.shape)

    lkd_hist = np.array(lkd_hist).reshape(len(lkd_hist), 1)
    lkd_hist = np.concatenate((lkd_hist, 1 - lkd_hist), axis=1)

    plkd_hist = np.array(plkd_hist).reshape(len(plkd_hist), 1)
    plkd_hist = np.concatenate((plkd_hist, 1 - plkd_hist), axis=1)

    Ypc = np.concatenate((lkd_hist, plkd_hist))

    fig, axes = plt.subplot()
    skplt.metrics.plot_roc(Y, Yp, classes_to_plot=[0], plot_micro=False, plot_macro=False, title="ROC Curve",ax=axes)
    skplt.metrics.plot_roc(Yc, Ypc, classes_to_plot=[0], plot_micro=False, plot_macro=False, title="ROC Curve",ax=axes)

    plt.savefig('./rocall.jpg')

    print("done")
