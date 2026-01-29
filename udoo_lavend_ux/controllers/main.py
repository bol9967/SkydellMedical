# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

import re
import logging

from lxml import etree
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)


class OmuxListController(http.Controller):
    @http.route('/omux/lcrv_parser', type='json', auth='user')
    def lookup_allow_forbid_group_ids(self, view_id, field):
        view = request.env['ir.ui.view'].sudo().browse(view_id)
        studio_view = self._get_mod_view(view)
        if not studio_view:
            return {'ugroup': request.env.user.groups_id.ids}

        arch = etree.fromstring(
            studio_view.arch_db, etree.XMLParser(remove_blank_text=True)
        )
        xpath_field = f"//field[@name='{field}' and not(@position)]"
        xpath_attrs = (
            f"//xpath[@expr=\"//field[@name='{field}']\" and @position='attributes']"
        )

        node_attrs = arch.xpath(xpath_attrs)
        xmlids = ''
        if node_attrs:
            node = node_attrs[0].xpath("//attribute[@name='groups']")
            xmlids = node[0].text if node else ''
        else:
            node = arch.xpath(xpath_field)
            if node:
                xmlids = node[0].get('groups')

        if not xmlids:
            return {'ugroup': request.env.user.groups_id.ids}

        allow_list, forbid_list = [], []
        for raw in xmlids.split(','):
            item = raw.strip()
            if item.startswith('!'):
                forbid_list.append(item[1:].strip())
            else:
                allow_list.append(item)

        pattern = re.compile(r'^[a-z][a-z0-9_]*\.[a-zA-Z0-9_]+$')
        for x in allow_list + forbid_list:
            if not pattern.match(x):
                return {'error': f'Invalid external ID format: {x}'}

        pairs = [tuple(x.split('.', 1)) for x in (allow_list + forbid_list)]
        ir_model_data = request.env['ir.model.data'].sudo()
        ir_model_data._cr.execute(
            """
            SELECT module, res_id, name
            FROM ir_model_data
            WHERE (module, name) IN %s
            """,
            (tuple(pairs),),
        )
        rows = ir_model_data._cr.fetchall()
        lookup = {f'{r[0]}.{r[2]}': r[1] for r in rows}

        missing = [x for x in (allow_list + forbid_list) if x not in lookup]
        if missing:
            return {'error': f'External ID(s) not found: {", ".join(missing)}'}

        return {
            'allow': [lookup[x] for x in allow_list],
            'forbid': [lookup[x] for x in forbid_list],
            'ugroup': request.env.user.groups_id.ids,
        }

    @http.route('/omux/restore_default_list_view', type='json', auth='user')
    def restore_default_list_view(self, view_id):
        if not request.env.user.has_group('udoo_lavend_ux.group_lvm'):
            raise Forbidden()

        view = request.env['ir.ui.view'].sudo().browse(view_id)
        self._set_mod_view(view, '')

    @http.route('/omux/edit_list_view', type='json', auth='user')
    def edit_list_view(self, view_id, operations=None):
        def _remp_node(node):
            parent = node.getparent()
            parent.remove(node)
            if not parent.getchildren():
                parent.getparent().remove(parent)

        if not request.env.user.has_group('udoo_lavend_ux.group_lvm'):
            raise Forbidden()

        view = request.env['ir.ui.view'].sudo().browse(view_id)
        studio_view = self._get_mod_view(view) or self._create_mod_view(view, '<data/>')

        parser = etree.XMLParser(remove_blank_text=True)
        arch = etree.fromstring(studio_view.arch_db, parser=parser)

        EXP_EXPR = "//field[@name='%s' and not(@position)]"
        MOV_EXPR = "//field[@name='%s' and @position='move']"
        for field, data in sorted(
            operations.items(), key=lambda item: item[1]['order']
        ):
            attrib_ok = True
            attrib_params = data.get('attrs') or {}

            ATT_EXPR = f"//xpath[@expr=\"//field[@name='{field}']\" and @position='attributes']"

            attribs, rem_attribs = {}, {}
            for attr in attrib_params:
                tribs = attrib_params[attr]
                if tribs:
                    attribs[attr] = tribs
                elif attr == 'string':
                    rem_attribs[attr] = True
                elif attr == 'optional':
                    if not arch.xpath(EXP_EXPR % field):
                        rem_attribs[attr] = True
                    else:
                        attribs[attr] = ''  # unset optional

            # Handles group-based visibility settings
            (attribs, rem_attribs) = self._process_group_access(
                attribs,
                rem_attribs,
                data.get('allow_group_ids'),
                data.get('forbid_group_ids'),
            )

            xml_node = etree.Element('field', attribs)

            if prev_node := data.get('prev_node'):
                exist_moves = arch.xpath(MOV_EXPR % field)
                if exist_moves:
                    for node in exist_moves:
                        _remp_node(node)

                if isinstance(prev_node, dict) and 'id' in prev_node:
                    prev_node = prev_node['id']
                    xml_node = etree.Element(
                        'field', {'name': field, 'position': 'move'}
                    )
                else:
                    attrib_ok = False

                exist_prevs = arch.xpath(EXP_EXPR % prev_node)
                if exist_prevs:
                    if exist_movs := arch.xpath(MOV_EXPR % prev_node):
                        exist_prevs = exist_movs
                    for node in exist_prevs:
                        parent = node.getparent()
                        parent.insert(parent.index(node) + 1, xml_node)
                        break
                else:
                    xpath_node = etree.SubElement(
                        arch,
                        'xpath',
                        {
                            'expr': f"//field[@name='{prev_node}']",
                            'position': 'after',
                        },
                    )
                    xpath_node.insert(0, xml_node)
            elif next_node := data.get('next_node'):
                exist_moves = arch.xpath(MOV_EXPR % field)
                if exist_moves:
                    for node in exist_moves:
                        _remp_node(node)

                if isinstance(next_node, dict) and 'id' in next_node:
                    next_node = next_node['id']
                    xml_node = etree.Element(
                        'field', {'name': field, 'position': 'move'}
                    )
                else:
                    attrib_ok = False

                exist_nexts = arch.xpath(EXP_EXPR % next_node)
                if exist_nexts:
                    if exist_movs := arch.xpath(MOV_EXPR % next_node):
                        exist_nexts = exist_movs
                    for node in exist_nexts:
                        parent = node.getparent()
                        parent.insert(parent.index(node), xml_node)
                        break
                else:
                    xpath_node = etree.SubElement(
                        arch,
                        'xpath',
                        {
                            'expr': f"//field[@name='{next_node}']",
                            'position': 'before',
                        },
                    )
                    xpath_node.insert(0, xml_node)
            elif data.get('replace'):
                attrib_ok = False

                exist_moves = arch.xpath(MOV_EXPR % field)
                if exist_moves:
                    for node in exist_moves:
                        _remp_node(node)

                exist_prevs = arch.xpath(EXP_EXPR % field)
                if exist_prevs:
                    for node in exist_prevs:
                        _remp_node(node)
                        break
                else:
                    etree.SubElement(
                        arch,
                        'xpath',
                        {
                            'expr': f"//field[@name='{field}']",
                            'position': 'replace',
                        },
                    )
                exist_att_xpaths = arch.xpath(ATT_EXPR)
                for node in exist_att_xpaths:
                    _remp_node(node)

            if attrib_ok:
                xpath_node = None
                if exist_fields := arch.xpath(EXP_EXPR % field):
                    exist_field = exist_fields[0]
                    for attr in attribs:
                        if attr == 'name':
                            continue
                        exist_field.set(attr, attribs[attr])

                elif exist_att_xpaths := arch.xpath(ATT_EXPR):
                    xpath_node = exist_att_xpaths[0]
                else:
                    xpath_node = etree.SubElement(
                        arch,
                        'xpath',
                        {
                            'expr': f"//field[@name='{field}']",
                            'position': 'attributes',
                        },
                    )

                if xpath_node is not None:
                    for attr in attribs:
                        if attr == 'name':
                            continue
                        if exist_attrs := xpath_node.xpath(
                            f"attribute[@name='{attr}']"
                        ):
                            exist_attrs[0].text = attribs[attr]
                        else:
                            xml_node = etree.Element('attribute', {'name': attr})
                            xml_node.text = attribs[attr]
                            xpath_node.insert(0, xml_node)

            for attr in rem_attribs:
                if exist_attrs := arch.xpath(f"//attribute[@name='{attr}']"):
                    for node in exist_attrs:
                        _remp_node(node)
                        break

        new_arch = etree.tostring(arch, encoding='unicode', pretty_print=True)
        self._set_mod_view(view, new_arch)

    def _process_group_access(self, attribs, rttribs, a_ids, f_ids):
        irmd = request.env['ir.model.data'].sudo()
        a_str, f_str = '', ''

        if a_ids:
            xmlid_str = irmd.search(
                [('model', '=', 'res.groups'), ('res_id', 'in', a_ids)]
            ).mapped('complete_name')
            a_str = ','.join(xmlid_str)

        if f_ids:
            xmlid_str = irmd.search(
                [('model', '=', 'res.groups'), ('res_id', 'in', f_ids)]
            ).mapped('complete_name')
            f_str = '!' + ',!'.join(xmlid_str)

        # If no allowed or forbidden groups are defined, mark the groups attribute for removal.
        if not a_str and not f_str:
            rttribs['groups'] = True
        else:
            attribs['groups'] = a_str + (',' if a_str and f_str else '') + f_str

        return (attribs, rttribs)

    def _generate_mod_name(self, view):
        return '[OMUX_CUSTOM] %s' % (view.xml_id)

    def _get_mod_view(self, view):
        domain = [
            ('inherit_id', '=', view.id),
            ('name', '=', self._generate_mod_name(view)),
        ]
        return view.search(domain, order='priority desc, name desc, id desc', limit=1)

    def _set_mod_view(self, view, arch):
        mod_view = self._get_mod_view(view)
        if mod_view and len(arch):
            mod_view.arch_db = arch
        elif mod_view:
            mod_view.unlink()
        elif len(arch):
            self._create_mod_view(view, arch)

    def _create_mod_view(self, view, arch):
        # To ensure our customization is applied last, we need to adjust the view priorities.
        # In Odoo, users interact with the final view after all inheritance layers are applied.
        # Therefore, any changes they make affect this final result. To reflect their changes correctly,
        # our customization must be the last one executed.
        priority = max(view.inherit_children_ids.mapped('priority'), default=0) * 9
        default_prio = view._fields['priority'].default(view)
        if priority <= default_prio:
            priority = 98
        return (
            request.env['ir.ui.view']
            .sudo()
            .create(
                {
                    'type': view.type,
                    'model': view.model,
                    'inherit_id': view.id,
                    'mode': 'extension',
                    'priority': priority,
                    'arch': arch,
                    'name': self._generate_mod_name(view),
                }
            )
        )
