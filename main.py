import numpy as np
import torch
from torch.utils.data import DataLoader
from torch import nn
from torch.nn import functional as F
import torchvision.transforms as transforms
from sklearn import metrics
import argparse
import timeit
import cv2

import datasets

class RandomGaussianBlur(object):
    def __call__(self, img):
        do_it = np.random.rand() > 0.5
        if not do_it:
            return img
        sigma = np.random.rand() * 1.9 + 0.1
        return cv2.GaussianBlur(np.asarray(img), (23, 23), sigma)

def get_color_distortion(s=1.0):
    # s is the strength of color distortion.
    color_jitter = transforms.ColorJitter(0.8 * s, 0.8 * s, 0.8 * s, 0.2 * s)
    rnd_color_jitter = transforms.RandomApply([color_jitter], p=0.8)
    rnd_gray = transforms.RandomGrayscale(p=0.2)
    color_distort = transforms.Compose([rnd_color_jitter, rnd_gray])
    return color_distort

def metric(y_true, y_pred, threshold=0.5):
    kappa = metrics.cohen_kappa_score(y_true, y_pred > threshold)
    f1 = metrics.f1_score(y_true, y_pred > threshold, average='micro')
    auc = metrics.roc_auc_score(y_true, y_pred)
    final_score = (kappa+f1+auc) / 3.0
    
    return final_score

def main(args):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('Using %s device.' % (device))

    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.228, 0.224, 0.225])
    # build the augmentations
    transform = transforms.Compose([
        transforms.RandomResizedCrop(224),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.Compose([
            get_color_distortion(),
            RandomGaussianBlur(),
            ]),
        transforms.ToTensor(),
        normalize,
        ])

    # init the dataset and augmentations
    train_dataset = datasets.ODIR5K('train', transform)
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0)

    test_dataset = datasets.ODIR5K('test', transform)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)

    net = torch.hub.load('facebookresearch/swav', 'resnet50')

    num_features = net.fc.in_features
    net.fc = nn.Sequential(
            nn.Linear(num_features, args.classes),
            nn.Sigmoid())

    if args.model_path:
        net.load_state_dict(torch.load(args.model_path, map_location=device))
        print('model state has loaded.')

    net = net.to(device)

    optimizer = torch.optim.Adam(net.parameters(), lr=args.lr)
    criterion = torch.nn.CrossEntropyLoss()

    net.train()
    for epoch in range(args.epochs):
        start_time = timeit.default_timer()
        y_true = torch.FloatTensor()
        y_pred = torch.FloatTensor()
        train_loss = 0
        for index, (left_images, right_images, labels) in enumerate(train_loader, 1):
            left_images = left_images.to(device)
            right_images = right_images.to(device)
            labels = labels.to(device)

            left_outputs = net(left_images)
            right_outputs = net(right_images)

            outputs = (left_outputs + right_outputs) / 2

            loss = criterion(outputs, labels)
            train_loss += loss.item()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            y_true = torch.cat((y_true, labels.cpu()))
            y_pred = torch.cat((y_pred, outputs.detach().cpu()))

            print('\repoch %3d/%3d batch %3d/%3d' % (epoch+1, args.epochs, index, len(train_loader)), end='')
            print(' loss %6.4f' % (train_loss / index), end='')
            print(' %6.3fsec' % (timeit.default_timer() - start_time), end='')

        aucs = [metrics.roc_auc_score(y_true[:, i], y_pred[:, i]) for i in range(args.classes)]
        auc_classes = ' '.join(['%5.3f' % (aucs[i]) for i in range(args.classes)])
        print(' average AUC %5.3f (%s)' % (np.mean(aucs), auc_classes))
        torch.save(net.state_dict(), 'model/checkpoint.pth')

    net.eval()
    start_time = timeit.default_timer()
    y_true = torch.FloatTensor()
    y_pred = torch.FloatTensor()
    test_loss = 0
    for index, (left_images, right_images, labels) in enumerate(test_loader, 1):
        left_images = left_images.to(device)
        right_images = right_images.to(device)
        labels = labels.to(device)

        with torch.no_grad():
            left_outputs = net(left_images)
            right_outputs = net(right_images)

        outputs = (left_outputs + right_outputs) / 2

        loss = criterion(outputs, labels)
        test_loss += loss.item()

        y_true = torch.cat((y_true, labels.cpu()))
        y_pred = torch.cat((y_pred, outputs.detach().cpu()))

        print('\rtest batch %3d/%3d' % (index, len(test_loader)), end='')
        print(' loss %6.4f' % (test_loss / index), end='')
        print(' %6.3fsec' % (timeit.default_timer() - start_time), end='')

    aucs = [metrics.roc_auc_score(y_true[:, i], y_pred[:, i]) for i in range(args.classes)]
    auc_classes = ' '.join(['%5.3f' % (aucs[i]) for i in range(args.classes)])
    print(' average AUC %5.3f (%s)' % (np.mean(aucs), auc_classes))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model_path', default=None, type=str)
    parser.add_argument('--epochs', default=150, type=int)
    parser.add_argument('--batch_size', default=32, type=int)
    parser.add_argument('--classes', default=8, type=int)
    parser.add_argument('--lr', default=1e-4, type=float) # 5e-5
    parser.add_argument('--momentum', default=0.9, type=float)
    args = parser.parse_args()
    print(vars(args))

    main(args)
