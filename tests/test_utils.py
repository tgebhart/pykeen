# -*- coding: utf-8 -*-

"""Tests for the :mod:`pykeen.utils` module."""

import string
import unittest

import torch

from pykeen.utils import (
    _CUDA_OOM_ERROR, _CUDNN_ERROR, clamp_norm, combine_complex, compact_mapping, flatten_dictionary,
    get_until_first_blank, is_cuda_oom_error, is_cudnn_error, project_entity, split_complex,
)


class FlattenDictionaryTest(unittest.TestCase):
    """Test flatten_dictionary."""

    def test_flatten_dictionary(self):
        """Test if the output of flatten_dictionary is correct."""
        nested_dictionary = {
            'a': {
                'b': {
                    'c': 1,
                    'd': 2,
                },
                'e': 3,
            },
        }
        expected_output = {
            'a.b.c': 1,
            'a.b.d': 2,
            'a.e': 3,
        }
        observed_output = flatten_dictionary(nested_dictionary)
        self._compare(observed_output, expected_output)

    def test_flatten_dictionary_mixed_key_type(self):
        """Test if the output of flatten_dictionary is correct if some keys are not strings."""
        nested_dictionary = {
            'a': {
                5: {
                    'c': 1,
                    'd': 2,
                },
                'e': 3,
            },
        }
        expected_output = {
            'a.5.c': 1,
            'a.5.d': 2,
            'a.e': 3,
        }
        observed_output = flatten_dictionary(nested_dictionary)
        self._compare(observed_output, expected_output)

    def test_flatten_dictionary_prefix(self):
        """Test if the output of flatten_dictionary is correct."""
        nested_dictionary = {
            'a': {
                'b': {
                    'c': 1,
                    'd': 2,
                },
                'e': 3,
            },
        }
        expected_output = {
            'Test.a.b.c': 1,
            'Test.a.b.d': 2,
            'Test.a.e': 3,
        }
        observed_output = flatten_dictionary(nested_dictionary, prefix='Test')
        self._compare(observed_output, expected_output)

    def _compare(self, observed_output, expected_output):
        assert not any(isinstance(o, dict) for o in expected_output.values())
        assert expected_output == observed_output


class TestGetUntilFirstBlank(unittest.TestCase):
    """Test get_until_first_blank()."""

    def test_get_until_first_blank_trivial(self):
        """Test the trivial string."""
        s = ''
        r = get_until_first_blank(s)
        self.assertEqual('', r)

    def test_regular(self):
        """Test a regulat case."""
        s = """Broken
        line.

        Now I continue.
        """
        r = get_until_first_blank(s)
        self.assertEqual("Broken line.", r)


class TestUtils(unittest.TestCase):
    """Tests for :mod:`pykeen.utils`."""

    def test_compact_mapping(self):
        """Test ``compact_mapping()``."""
        mapping = {
            letter: 2 * i
            for i, letter in enumerate(string.ascii_letters)
        }
        compacted_mapping, id_remapping = compact_mapping(mapping=mapping)

        # check correct value range
        self.assertEqual(set(compacted_mapping.values()), set(range(len(mapping))))
        self.assertEqual(set(id_remapping.keys()), set(mapping.values()))
        self.assertEqual(set(id_remapping.values()), set(compacted_mapping.values()))

    def test_clamp_norm(self):
        """Test :func:`pykeen.utils.clamp_norm`."""
        max_norm = 1.0
        gen = torch.manual_seed(42)
        eps = 1.0e-06
        for p in [1, 2, float('inf')]:
            for _ in range(10):
                x = torch.rand(10, 20, 30, generator=gen)
                for dim in range(x.ndimension()):
                    x_c = clamp_norm(x, maxnorm=max_norm, p=p, dim=dim)

                    # check maximum norm constraint
                    assert (x_c.norm(p=p, dim=dim) <= max_norm + eps).all()

                    # unchanged values for small norms
                    norm = x.norm(p=p, dim=dim)
                    mask = torch.stack([(norm < max_norm)] * x.shape[dim], dim=dim)
                    assert (x_c[mask] == x[mask]).all()

    def test_complex_utils(self):
        """Test complex tensor utilities."""
        re = torch.rand(20, 10)
        im = torch.rand(20, 10)
        x = combine_complex(x_re=re, x_im=im)
        re2, im2 = split_complex(x)
        assert (re2 == re).all()
        assert (im2 == im).all()

    def test_project_entity(self):
        """Test _project_entity."""
        batch_size = 2
        embedding_dim = 3
        relation_dim = 5
        num_entities = 7

        # random entity embeddings & projections
        e = torch.rand(1, num_entities, embedding_dim)
        e = clamp_norm(e, maxnorm=1, p=2, dim=-1)
        e_p = torch.rand(1, num_entities, embedding_dim)

        # random relation embeddings & projections
        r_p = torch.rand(batch_size, 1, relation_dim)

        # project
        e_bot = project_entity(e=e, e_p=e_p, r_p=r_p)

        # check shape:
        assert e_bot.shape == (batch_size, num_entities, relation_dim)

        # check normalization
        assert (torch.norm(e_bot, dim=-1, p=2) <= 1.0 + 1.0e-06).all()

        # check equivalence of re-formulation
        # e_{\bot} = M_{re} e = (r_p e_p^T + I^{d_r \times d_e}) e
        #                     = r_p (e_p^T e) + e'
        m_re = r_p.unsqueeze(dim=-1) @ e_p.unsqueeze(dim=-2)
        m_re = m_re + torch.eye(relation_dim, embedding_dim).view(1, 1, relation_dim, embedding_dim)
        assert m_re.shape == (batch_size, num_entities, relation_dim, embedding_dim)
        e_vanilla = (m_re @ e.unsqueeze(dim=-1)).squeeze(dim=-1)
        e_vanilla = clamp_norm(e_vanilla, p=2, dim=-1, maxnorm=1)
        assert torch.allclose(e_vanilla, e_bot)


class TestCudaExceptionsHandling(unittest.TestCase):
    """Test handling of CUDA exceptions."""

    not_cuda_error = RuntimeError("Something else.")

    def test_is_cuda_oom_error(self):
        """Test handling of a CUDA out of memory exception."""
        error = RuntimeError(_CUDA_OOM_ERROR)
        self.assertTrue(is_cuda_oom_error(runtime_error=error))
        self.assertFalse(is_cudnn_error(runtime_error=error))

        self.assertFalse(is_cuda_oom_error(runtime_error=self.not_cuda_error))

    def test_is_cudnn_error(self):
        """Test handling of a cuDNN error."""
        error = RuntimeError(_CUDNN_ERROR)
        self.assertTrue(is_cudnn_error(runtime_error=error))
        self.assertFalse(is_cuda_oom_error(runtime_error=error))

        self.assertFalse(is_cudnn_error(runtime_error=self.not_cuda_error))
