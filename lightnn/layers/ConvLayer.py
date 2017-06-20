# -*- encoding:utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys

import numpy as np

from ..base.BasicFunctions import sigmoid, delta_sigmoid, identity, delta_identity
from ..base.BasicFunctions import Sigmoid, Relu, Identity
from ..base.Costs import CECost
from ..base.Initializers import xavier_weight_initializer
from ..ops import _check_convolution_layer


class Filter(object):
    def __init__(self, filter_height, filter_width, filter_channel, initializer):
        self.filter_height = filter_height
        self.filter_width = filter_width
        self.filter_channel = filter_channel
        self.__W = initializer([filter_height, filter_width, filter_channel])
        self.__b = 0.
        self.__delta_W = np.zeros([filter_height, filter_width, filter_channel])
        self.__delta_b = 0.

    @property
    def W(self):
        return self.__W

    @property
    def b(self):
        return self.__b

    @property
    def delta_W(self):
        return self.__delta_W

    @property
    def delta_b(self):
        return self.__delta_b

    @W.setter
    def W(self, W):
        self.__W = W

    @b.setter
    def b(self, b):
        self.__b = b

    @delta_W.setter
    def delta_W(self, delta_W):
        self.__delta_W = delta_W

    @delta_b.setter
    def delta_b(self, delta_b):
        self.__delta_b = delta_b

    def update(self):
        self.__W -= self.__delta_W
        self.__b -= self.__delta_b



class ConvLayer(object):
    def __init__(self, input_height, input_width, input_channel,
                 filter_height, filter_width, filter_num,
                 zero_padding=0, stride=1, activator=Relu, initializer=xavier_weight_initializer, lr=1e-1):
        """
        Convolution Layer
        :param input_height: the input picture's height
        :param input_width: the input picture's width
        :param input_channel: the input pictures's channel number
        :param filter_height: the filter's height
        :param filter_width: the filter's width
        :param filter_num: the number of filters used in this layer
        :param zero_padding: zero padding number, int or tuple
        :param stride: int or tuple, given (stride_height, stride_width) or stride
                        to control the size of output picture
        :param activator: activator like tanh or sigmoid or relu
        """

        if isinstance(zero_padding, int):
            zero_padding = (zero_padding, zero_padding)
        input_height, input_width, input_channel, filter_height, \
        filter_width, filter_num, zero_padding, stride = \
            _check_convolution_layer(input_height, input_width, input_channel,
                                     filter_height, filter_width, filter_num,
                                     zero_padding, stride)
        self.input_height = input_height
        self.input_width = input_width
        self.input_channel = input_channel
        self.filter_height = filter_height
        self.filter_width = filter_width
        self.filter_num = filter_num
        self.filters = [Filter(filter_height, filter_width, input_channel, initializer)
                            for _ in xrange(filter_num)]
        self.zero_padding = zero_padding
        self.output_height = self._calc_output_size(input_height, filter_height, stride[0], zero_padding[0])
        self.output_width = self._calc_output_size(input_width, filter_width, stride[1], zero_padding[1])
        self.output_channel = filter_num
        self.output = np.zeros([self.output_height, self.output_width, self.output_channel])
        self.activator = activator
        self.stride = stride if isinstance(stride, list) or isinstance(stride, tuple) \
                                else (stride, stride)
        self.__delta = np.zeros((self.input_width, self.input_height,
                               self.input_channel))
        self.lr = lr

    @property
    def delta(self):
        return self.__delta

    @property
    def W(self):
        return [filter.W for filter in self.filters]

    @property
    def b(self):
        return [filter.b for filter in self.filters]

    def forward(self, input):
        self.input = input
        self.padded_input = self._padding(self.input, self.zero_padding)

        for o_c, filter in enumerate(self.filters):
            filter_W = filter.W
            filter_b = filter.b
            self._conv(self.padded_input, filter_W, self.output[:,:,o_c], filter_b, self.stride)

        self.output = self.activator.forward(self.output)
        return self.output

    def backward(self, pre_delta_map):
        expanded_pre_delta_map = self.__expand_sensitive_map(pre_delta_map)
        expanded_height, expanded_width, expanded_channel = expanded_pre_delta_map.shape
        # expanded_height + 2*pad - filter_height + 1 = input_height
        zero_padding = [0, 0]
        zero_padding[0] = (self.input_height + self.filter_height - expanded_height - 1) // 2
        zero_padding[1] = (self.input_width + self.filter_width - expanded_width - 1) // 2
        zero_padding[0] = max(0, zero_padding[0])
        zero_padding[1] = max(0, zero_padding[1])
        padded_delta_map = self._padding(expanded_pre_delta_map, zero_padding)


        for i, filter in enumerate(self.filters):
            rot_weights = np.zeros(filter.W.shape)
            for c in xrange(rot_weights.shape[2]):
                rot_weights[:,:,c] = np.rot90(filter.W[:,:,c], 2)
            delta_a = np.zeros((self.input_height, self.input_width,
                              self.input_channel))
            for i_c in xrange(self.input_channel):
                # calculate delta_{l-1}
                self._conv(padded_delta_map[:,:,i], rot_weights[:,:,i_c], delta_a[:,:,i_c], 0, (1, 1))
                # calclulate gradient of w
                self._conv(self.padded_input[:,:,i_c], expanded_pre_delta_map[:,:,i], filter.delta_W[:,:,i_c], 0, (1, 1))
            filter.delta_b = np.sum(expanded_pre_delta_map[:,:,i])
            self.__delta += delta_a
        # backward delta_{l-1}
        self.__delta *= self.activator.backward(self.input)
        return self.delta

    def _calc_output_size(self, input_len, filter_len, stride, zero_padding):
        return (input_len + 2 * zero_padding - filter_len) // stride + 1

    def _padding(self, inputs, zero_padding):
        inputs = np.asarray(inputs)
        if list(zero_padding) == [0, 0]:
            return inputs

        if inputs.ndim == 2:
            inputs = inputs[:,:,None]

        if inputs.ndim == 3:
            input_height, input_width, input_channel = inputs.shape
            padded_input = np.zeros([input_height + 2 * zero_padding[0],
                             input_width + 2 * zero_padding[1], input_channel])
            padded_input[zero_padding[0]:input_height + zero_padding[0],
                            zero_padding[1]:input_width + zero_padding[1], :] = inputs
            return padded_input
        else:
            raise ValueError('Your input must be a 2-D or 3-D tensor.')

    def _conv(self, inputs, filter_W, outputs, filter_b, stride):
        inputs = np.asarray(inputs)
        if inputs.ndim == 2:
            inputs = inputs[:,:,None]
        elif inputs.ndim == 3:
            inputs = inputs
        else:
            raise ValueError('Your input must be a 2-D or 3-D tensor.')
        if filter_W.ndim == 2:
            filter_W = filter_W[:,:,None]
        elif filter_W.ndim == 3:
            filter_W = filter_W
        else:
            raise ValueError('Your filter_W must be a 2-D or 3-D tensor.')

        i_height, i_width, _ = inputs.shape
        o_height, o_width = outputs.shape
        stride_height, stride_width = stride
        f_height, f_width, _ = filter_W.shape
        bw = bh = 0
        eh = f_height; ew = f_width
        for idx_height in xrange(o_height):
            for idx_width in xrange(o_width):
                if eh > i_height or ew > i_width:
                    break
                outputs[idx_height,idx_width] = \
                        np.sum(inputs[bh:eh,bw:ew,:] * filter_W) + filter_b
                bw += stride_width
                ew += stride_width
            bh += stride_height
            eh += stride_height
            bw = 0; ew = f_width

    def __expand_sensitive_map(self, pre_delta_map):
        height, width, depth = pre_delta_map.shape
        stride_height, stride_width = self.stride
        expanded_height = (height - 1) * stride_height + 1
        expanded_width = (width - 1) * stride_width + 1

        expanded_pre_delta_map = np.zeros([expanded_height, expanded_width, depth])

        for i in xrange(height):
            for j in xrange(width):
                expanded_pre_delta_map[stride_height * i,
                            stride_width * j, :] = pre_delta_map[i,j,:]
        return expanded_pre_delta_map

    def update(self):
        for filter in self.filters:
            filter.delta_W *= self.lr
            filter.delta_b *= self.lr
            filter.update()