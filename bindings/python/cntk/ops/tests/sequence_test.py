# Copyright (c) Microsoft. All rights reserved.

# Licensed under the MIT license. See LICENSE.md file in the project root
# for full license information.
# ==============================================================================

"""
Unit tests for the sequence_softmax.
"""

import numpy as np
import pytest
import cntk as C
from .. import *
from cntk.losses import *
from ...axis import Axis
from ... import sequence, input, placeholder, times
from cntk import Value
from cntk.internal import sanitize_dtype_cntk
from .ops_test_utils import cntk_device, AA, precision, PRECISION_TO_TYPE
from cntk.tests.test_utils import _to_dense, _to_csr


def test_lstm_over_lstm_thought_vectors(device_id):
    dev = cntk_device(device_id)
    input_vocab_size=3
    emb_dim = 2
    hidden_dim = 2
    num_labels = 2
    x_seq_input = C.sequence.input((C.FreeDimension, input_vocab_size), is_sparse=True, name='features')
    label_seq_input = C.sequence.input(num_labels, is_sparse=True, sequence_axis=Axis('label_sequence'), name='labels')
    with C.default_options(initial_state=0.1):
        model = C.layers.Embedding(emb_dim, name='embed')(x_seq_input)
        model = C.layers.Recurrence(C.layers.LSTM(hidden_dim), go_backwards=False)(model)
        model = C.sequence.last(model)
        model = C.to_sequence_like(model, label_seq_input)
        model = C.layers.Recurrence(C.layers.LSTM(hidden_dim), go_backwards=False)(model)
        model = C.layers.Dense(num_labels, name='classify')(model)

    z = model
    ce = C.cross_entropy_with_softmax(z, label_seq_input)

    seq1_data = [[[0, 1, 1], [0, 1, 0], [1, 0, 0]], [[1, 1, 0], [0, 0, 1], [1, 0, 1]], [[1, 0, 0], [0, 0, 1], [1, 1, 0]]]
    csr_seq1 = _to_csr(seq1_data)
    ndarrayview1 = C.NDArrayView.from_csr(csr_seq1, shape=(3, 3, 3), device=C.cpu())
    seq2_data = [[[0, 0, 1], [0, 1, 1], [1, 0, 1]], [[0, 1, 0], [1, 0, 1], [0, 0, 0]]]
    csr_seq2 = _to_csr(seq2_data)
    ndarrayview2 = C.NDArrayView.from_csr(csr_seq2, shape=(2, 3, 3), device=C.cpu())
    x_seq_data = C.Value.create(C.sequence.input((3, 3), is_sparse=True), [ndarrayview1, ndarrayview2], device=C.cpu()).data

    seq1_label_data = [[0, 1], [0, 1], [1, 0]]
    seq2_label_data = [[1, 0], [0, 1]]
    label_seq_data = [_to_csr(seq1_label_data), _to_csr(seq2_label_data)]
    param_grads, loss_result = ce.grad({x_seq_input : x_seq_data, label_seq_input : label_seq_data},
                                       wrt=ce.parameters, outputs=[ce], as_numpy=False)
    
    loss_result = loss_result.as_sequences()

    # TODO: The tolerance here is inordinately high due to the non-determinism in initialization 
    # of parameters as the individual tests are not run in separate processes resulting in the
    # addition or removal of tests to affect the random initialization of parameters in all other
    # tests that do not explicitly specify the random seed. The tolerance should be lowered to 
    # 0.01 after this issue in the test infrastructure has been fixed.
    absolute_tolerance = 0.02
    assert np.allclose(loss_result[0], [[0.63504], [0.673343], [0.698446]], atol=absolute_tolerance)
    assert np.allclose(loss_result[1], [[0.772344], [0.64295]], atol=absolute_tolerance)


def test_sequence_max():
  np.random.seed(0)
  a = np.float32(np.random.rand(20,100,8))
  src = sequence.input(shape=(8), sequence_axis=Axis("Seq"))
  out = sequence.reduce_max(src)
  val = out.eval({src:a})
  expected = np.max(a, 1) 
  assert np.allclose(val, expected)

def test_neg_sequence_max():
  np.random.seed(0)
  a = np.float32(-np.random.rand(20,100,8))
  src = sequence.input(shape=(8), sequence_axis=Axis("Seq"))
  out = sequence.reduce_max(src)
  val = out.eval({src:a})
  expected = np.max(a, 1) 
  assert np.allclose(val, expected)

def np_softmax(a):
  m = np.max(a, 1, keepdims=True)
  e = np.exp((a-m))
  s = np.sum(e,1, keepdims=True)
  return e/s
  
def test_sequence_softmax():
  np.random.seed(0)
  a = np.float32(np.random.rand(20,100,8))
  src = sequence.input(shape=(8), sequence_axis=Axis("Seq"))
  out = sequence.softmax(src)
  val = out.eval({src:a})
  expected = np_softmax(a)
  assert np.allclose(val, expected)


def test_to_sequence_basic(device_id):
    dev = cntk_device(device_id)
    x = C.input((C.FreeDimension, 2))
    x_seq = C.to_sequence(x)
    assert len(x_seq.dynamic_axes) == 2

    x_data = np.asarray([[[1, 2], [-1000, -1000]], [[3, 4], [5, 6]]], dtype=np.float32)
    result = x_seq.eval({x : x_data}, device=dev)
    assert np.array_equal(result, x_data)

    x = C.input((C.FreeDimension, 2, 3), is_sparse=True)
    x_seq_lens = C.input(())
    x_seq = C.to_sequence(x, x_seq_lens)
    
    seq1_data = [[[0, 1, 1], [0, 1, 0]], [[1, 0, 0], [1, 0, 1]]]
    csr_seq1 = _to_csr(seq1_data)
    ndarrayview1 = C.NDArrayView.from_csr(csr_seq1, shape=(2, 2, 3), device=C.cpu())
    seq2_data = [[0, 1, 1], [1, 1, 0]]
    csr_seq2 = _to_csr([seq2_data, [[0, 0, 0], [0, 0, 0]]])
    ndarrayview2 = C.NDArrayView.from_csr(csr_seq2, shape=(2, 2, 3), device=C.cpu())

    x_data = C.Value.create(C.input((2, 2, 3), is_sparse=True), [ndarrayview1, ndarrayview2], device=dev).data
    x_seq_lens_data = np.asarray([2, 1], dtype=np.float32)
    result = x_seq.eval({x : x_data, x_seq_lens : x_seq_lens_data}, device=dev, as_numpy=False)
    result_dense = _to_dense(result, True)
    assert np.array_equal(result_dense[0], seq1_data)
    assert np.array_equal(result_dense[1], [seq2_data])


def test_to_sequence_backprop(device_id):
    dev = cntk_device(device_id)
    input_vocab_size=3
    emb_dim = 2
    hidden_dim = 2
    num_labels = 2
    x_seq_input = C.sequence.input(input_vocab_size, is_sparse=True, name='features')
    with C.default_options(initial_state=0.1):
        model = C.layers.Embedding(emb_dim, name='embed')(x_seq_input)
        model = C.layers.Recurrence(C.layers.LSTM(hidden_dim), go_backwards=False)(model)
        model = C.layers.Dense(num_labels, name='classify')(model)

    z = model
    label_seq_input = C.sequence.input(num_labels, is_sparse=True, name='labels')
    ce = C.cross_entropy_with_softmax(z, label_seq_input)

    seq1_data = [[0, 1, 1], [0, 1, 0], [1, 0, 0]]
    seq2_data = [[0, 0, 1], [0, 1, 1]]
    seq1_label_data = [[0, 1], [0, 1], [1, 0]]
    seq2_label_data = [[1, 0], [0, 1]]
    label_seq_data = [_to_csr(seq1_label_data), _to_csr(seq2_label_data)]
    param_grads_1, loss_result_1 = ce.grad({x_seq_input : [_to_csr(seq1_data), _to_csr(seq2_data)], label_seq_input : label_seq_data},
                                           wrt=ce.parameters, outputs=[ce], as_numpy=False)
    
    # Create a clone of the model that uses a non-sequence input 
    # and converts it to a sequence using to_sequence
    x_non_seq_input = C.input((C.FreeDimension, input_vocab_size), is_sparse=True, name='non_seq_features')
    x_seq_lens = C.input((), name='sequence_lengths')
    x_seq = C.to_sequence(x_non_seq_input, x_seq_lens)
    x_seq = C.reconcile_dynamic_axes(C.times(x_seq, np.eye(input_vocab_size, dtype=np.float32)), label_seq_input)
    ce_clone = ce.clone('share', {x_seq_input : x_seq})

    x_non_seq_data = C.NDArrayView.from_csr(_to_csr([seq1_data, seq2_data + [[0, 0, 0]]]), shape=(2, 3, 3))
    x_seq_lens_data = np.asarray([3, 2], dtype=np.float32)

    x_non_seq_input = next(argument for argument in ce_clone.arguments if argument.name == 'non_seq_features')
    label_seq_input = next(argument for argument in ce_clone.arguments if argument.name == 'labels')
    x_seq_lens = next(argument for argument in ce_clone.arguments if argument.name == 'sequence_lengths')
    param_grads_2, loss_result_2 = ce_clone.grad({x_non_seq_input : x_non_seq_data, x_seq_lens : x_seq_lens_data, label_seq_input : label_seq_data},
                                                 wrt=ce_clone.parameters, outputs=[ce_clone], as_numpy=False)


    assert np.array_equal(loss_result_1.as_sequences()[0], loss_result_2.as_sequences()[0])
    assert np.array_equal(loss_result_1.as_sequences()[1], loss_result_2.as_sequences()[1])
    
    for param in param_grads_1:
        if not param_grads_1[param].is_sparse:
            reference_grad_value = param_grads_1[param].asarray()
            grad_value = param_grads_2[param].asarray()
            assert np.array_equal(reference_grad_value, grad_value)


def test_sequence_unpack_basic(device_id):
    dev = cntk_device(device_id)

    # Unpack a placeholder
    p = C.placeholder()
    p_unpacked_outputs = C.sequence.unpack(p, padding_value=0).outputs
    assert len(p_unpacked_outputs) == 2

    x = C.input((C.FreeDimension, 2, 3), is_sparse=False)
    x_seq_lens = C.input(())
    x_seq = C.to_sequence(x, x_seq_lens)
    x_seq_unpacked = C.sequence.unpack(x_seq, padding_value=-1000.0)
    x_seq_unpacked_value_output = x_seq_unpacked.outputs[0]
    x_seq_unpacked_mask_output = x_seq_unpacked.outputs[1]
    assert len(x_seq_unpacked_value_output.dynamic_axes) == 1
    assert x_seq_unpacked_value_output.shape == (C.FreeDimension, 2, 3)

    seq1_data = [[[0, 1, 1], [0, 1, 0]], [[1, 0, 0], [1, 0, 1]]]
    seq2_data = [[0, 1, 1], [1, 1, 0]]
    x_data = [np.asarray(seq1_data, dtype=np.float32), np.asarray([seq2_data, [[-100.0, -100.0, -100.0], [-100.0, -100.0, -100.0]]], dtype=np.float32)]
    x_seq_lens_data = np.asarray([2, 1], dtype=np.float32)
    result = x_seq_unpacked.eval({x : x_data, x_seq_lens : x_seq_lens_data}, device=dev)
    value = result[x_seq_unpacked_value_output]
    mask = result[x_seq_unpacked_mask_output]
    assert np.array_equal(value[0], seq1_data)
    assert np.array_equal(value[1], [seq2_data, [[-1000.0, -1000.0, -1000.0], [-1000.0, -1000.0, -1000.0]]])
    assert np.array_equal(mask, [[1, 1], [1, 0]])


def test_sequence_unpack_backprop(device_id):
    dev = cntk_device(device_id)
    input_vocab_size=3
    emb_dim = 2
    hidden_dim = 2
    num_labels = 2
    x_seq_input = C.sequence.input(input_vocab_size, is_sparse=True, name='features')
    label_input = C.input(num_labels, is_sparse=True, name='labels')
    with C.default_options(initial_state=0.1):
        model = C.layers.Embedding(emb_dim, name='embed')(x_seq_input)
        model = C.layers.Recurrence(C.layers.LSTM(hidden_dim), go_backwards=False)(model)
        model = C.layers.Dense(num_labels, name='classify')(model)

    z = C.sequence.last(C.layers.Recurrence(C.plus)(model))
    ce = C.cross_entropy_with_softmax(z, label_input)
    seq1_data = [[0, 1, 1], [0, 1, 0], [1, 0, 0]]
    seq2_data = [[0, 0, 1], [0, 1, 1]]
    label_data = _to_csr([[0, 1], [1, 0]])
    param_grads_1, loss_result_1 = ce.grad({x_seq_input : [_to_csr(seq1_data), _to_csr(seq2_data)], label_input : label_data},
                                           wrt=ce.parameters, outputs=[ce], as_numpy=False)
    
    z = C.sequence.reduce_sum(model)
    ce = C.cross_entropy_with_softmax(z, label_input)
    param_grads_2, loss_result_2 = ce.grad({x_seq_input : [_to_csr(seq1_data), _to_csr(seq2_data)], label_input : label_data},
                                           wrt=ce.parameters, outputs=[ce], as_numpy=False)

    assert np.array_equal(loss_result_1.asarray(), loss_result_2.asarray())
    
    for param in param_grads_1:
        if not param_grads_1[param].is_sparse:
            reference_grad_value = param_grads_1[param].asarray()
            grad_value = param_grads_2[param].asarray()
            assert np.array_equal(reference_grad_value, grad_value)

def test_to_sequence_error_for_operand_with_sequence_axis():
    x = C.sequence.input(C.FreeDimension, 2)
    with pytest.raises(ValueError):
        op = C.to_sequence(x)


def test_sequence_reduce_sum_over_scalar():
    x = C.sequence.input(shape=(), needs_gradient=True)
    op = C.sequence.reduce_sum(x)

    grad, result = op.grad({x : [np.asarray([-1, 3, 5], dtype=np.float32), np.asarray([2, -5], dtype=np.float32), np.asarray([-2], dtype=np.float32)]}, outputs=[op])
    assert np.array_equal(result, [7, -3, -2])
    assert np.array_equal(grad[0], [1, 1, 1])
    assert np.array_equal(grad[1], [1, 1])
    assert np.array_equal(grad[2], [1])


def test_sequence_reduce_over_reduced_scalar():
    x = C.sequence.input(shape=(1), needs_gradient=True)
    op = C.sequence.reduce_sum(C.reduce_sum(x))

    grad, result = op.grad({x : np.asarray([[-1], [3], [5]], dtype=np.float32)}, outputs=[op])
    assert np.array_equal(result, [7])
    assert np.array_equal(grad[0], [[1], [1], [1]])

def test_op_broadcast_as(device_id, precision):

    a_data = [AA([1], dtype=PRECISION_TO_TYPE[precision]),
              AA([2], dtype=PRECISION_TO_TYPE[precision]),
              AA([3], dtype=PRECISION_TO_TYPE[precision])]
    b_data = [AA([[2]], dtype=PRECISION_TO_TYPE[precision]),
              AA([[2], [3]], dtype=PRECISION_TO_TYPE[precision]),
              AA([[2], [3], [4]], dtype=PRECISION_TO_TYPE[precision])]

    a = C.input(shape=(1,), dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]), name='a')
    b = sequence.input(shape=(1,), dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]), name='b')

    broadcast_a_as_b = sequence.broadcast_as(a, b)

    res = broadcast_a_as_b.eval({a: a_data, b: b_data})
    assert np.array_equal(res[0], np.asarray([[1.]]))
    assert np.array_equal(res[1], np.asarray([[2.], [2.]]))
    assert np.array_equal(res[2], np.asarray([[3.], [3.], [3.]]))


def test_op_broadcast_as_in_loop(device_id):

    a_data = [AA([1]), AA([2]), AA([3])]
    b_data = [AA([[2]]), AA([[2], [3]]), AA([[2], [3], [4]])]

    a = C.input(shape=(1,), name='a')
    b = sequence.input(shape=(1,), name='b')

    out_placeholder = placeholder()
    out_delayed = sequence.past_value(out_placeholder, time_step=5)
    out_delayed_plus_b = out_delayed + b
    out = sequence.broadcast_as(a, out_delayed_plus_b)
    out.replace_placeholder(out)

    res = out.eval({a: a_data, b: b_data})
    assert np.array_equal(res[0], np.asarray([[1.]]))
    assert np.array_equal(res[1], np.asarray([[2.], [2.]]))
    assert np.array_equal(res[2], np.asarray([[3.], [3.], [3.]]))

def test_op_gather_dynamic_axes_equivalence(device_id, precision):
    input_data1 = AA([1], dtype=PRECISION_TO_TYPE[precision])
    input_data2 = AA([2], dtype=PRECISION_TO_TYPE[precision])

    a = sequence.input(shape=input_data1.shape,
                       dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]),
                       name='a')
    b = sequence.input(shape=input_data2.shape,
                       dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]),
                       name='b')

    is_last_a = sequence.is_last(a)
    a_last = sequence.gather(a, is_last_a)
    b_last = sequence.gather(b, is_last_a)
    z = a_last + b_last

    # create batch
    input_data1.shape = (1, 1) + input_data1.shape
    input_data2.shape = (1, 1) + input_data2.shape

    res = z.eval({a: input_data1, b: input_data2})
    expected_forward = [[[3.]]]
    assert np.array_equal(res, expected_forward)


def test_op_gather_derived_dynamic_axes_equivalence(device_id, precision):
    input_data1 = AA([1], dtype=PRECISION_TO_TYPE[precision])
    input_data2 = AA([2], dtype=PRECISION_TO_TYPE[precision])

    a = sequence.input(shape=input_data1.shape,
                       dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]),
                       name='a')
    b = sequence.input(shape=input_data2.shape,
                       dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]),
                       name='b')

    a_last = sequence.gather(a, sequence.is_last(a), new_sequence_axis_typeinfo=(0, 1))
    b_last = sequence.gather(b, sequence.is_last(b), new_sequence_axis_typeinfo=(0, 1))

    z = a_last + b_last

    # create batch
    input_data1.shape = (1, 1) + input_data1.shape
    input_data2.shape = (1, 1) + input_data2.shape

    res = z.eval({a: input_data1, b: input_data2})
    expected_forward = [[3.]]
    assert np.array_equal(res, expected_forward)


def test_op_gather_sparse(device_id):
    input_sparse_indices = [[1, 3, 5, 5], [2, 4], [0, 2]]
    vocab_size = 6
    input_data = Value.one_hot(input_sparse_indices, vocab_size)

    a = sequence.input(shape=(vocab_size,), is_sparse=True, name='a')

    a_last = sequence.last(a)
    a_last_dense = times(a_last, np.eye(vocab_size))
    res = a_last_dense.eval({a : input_data})
    assert np.array_equal(res, [[0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 1, 0], [0, 0, 1, 0, 0, 0]])

    a_last_2 = sequence.slice(a, -2, 0)
    a_last_2_dense = times(a_last_2, np.eye(vocab_size))
    res = a_last_2_dense.eval({a : input_data})
    assert np.array_equal(res, [[[0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, 1]], [[0, 0, 1, 0, 0, 0], [0, 0, 0, 0, 1, 0]], [[1, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 0]]])


def test_op_scatter_sparse(device_id):
    input_sparse_indices = [[1, 3, 5, 5], [2, 4], [0, 2]]
    vocab_size = 6
    input_data = Value.one_hot(input_sparse_indices, vocab_size)

    a = sequence.input(shape=(vocab_size,), is_sparse=True, name='a')

    a_last_scatter = sequence.scatter(sequence.last(a), sequence.is_first(a))
    a_last_scatter_dense = times(a_last_scatter, np.eye(vocab_size))
    res = a_last_scatter_dense.eval({a : input_data})
    assert np.array_equal(res[0], np.asarray([[0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]]))
    assert np.array_equal(res[1], np.asarray([[0, 0, 0, 0, 1, 0], [0, 0, 0, 0, 0, 0]]))
    assert np.array_equal(res[2], np.asarray([[0, 0, 1, 0, 0, 0], [0, 0, 0, 0, 0, 0]]))


def test_op_sequence_reduce_sum(device_id, precision):
    a = sequence.input(shape=(1,), dtype=sanitize_dtype_cntk(PRECISION_TO_TYPE[precision]), needs_gradient=True, name='a')

    sequence_sum_a_plus_sequence_sum_a = sequence.reduce_sum(a) + sequence.reduce_sum(a)

    a_data = [AA([[2]], dtype=PRECISION_TO_TYPE[precision]),
              AA([[2], [3]], dtype=PRECISION_TO_TYPE[precision]),
              AA([[2], [3], [4]], dtype=PRECISION_TO_TYPE[precision])]

    actual_grad = sequence_sum_a_plus_sequence_sum_a.grad({a: a_data}, [a])
    assert np.array_equal(actual_grad[0], np.asarray([[2.]]))
    assert np.array_equal(actual_grad[1], np.asarray([[2.], [2.]]))
    assert np.array_equal(actual_grad[2], np.asarray([[2.], [2.], [2.]]))

    res = sequence_sum_a_plus_sequence_sum_a.eval({a: a_data})
    assert np.array_equal(res[0], np.asarray([4.]))
    assert np.array_equal(res[1], np.asarray([10.]))
    assert np.array_equal(res[2], np.asarray([18.]))

    # Verify that calling sequence reduction on a placeholder with known
    # shape but unknown dynamic axes does not result in a problem
    p = C.placeholder(shape=(1,))
    r = sequence.reduce_sum(p)
    r.replace_placeholder(a)

    res = r.eval({a: a_data})
    assert np.array_equal(res[0], np.asarray([2.]))
    assert np.array_equal(res[1], np.asarray([5.]))
    assert np.array_equal(res[2], np.asarray([9.]))
